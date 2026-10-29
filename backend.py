"""Experimental streaming audio.cpp backend for Calibre. GPL-3.0-or-later."""
import atexit
import json
import os
import time
from collections import deque
from pathlib import Path

from qt.core import (
    QApplication, QAudio, QAudioFormat, QAudioSink, QIODevice, QIODeviceBase,
    QMediaDevices, QNetworkAccessManager, QNetworkRequest, QTimer, QTextToSpeech, QUrl,
)
from calibre.constants import config_dir
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, SpeechEvents, WaveResponse, speech_request, model_family, CLONED_VOICE, PLUGIN_VOICE
from calibre_plugins.audio_cpp_read_aloud.settings import load as load_plugin_settings
from calibre.gui2.tts.types import EngineSpecificSettings, TTSBackend, Voice
from calibre.spell.break_iterator import PARAGRAPH_SEPARATOR, split_into_sentences_for_tts


class AudioCpp(TTSBackend):
    engine_name = 'audiocpp_plugin'
    filler_char = PARAGRAPH_SEPARATOR

    def __init__(self, engine_name='', parent=None, config_name='tts', preview_config=None):
        super().__init__(engine_name, parent)
        self.preview_config = preview_config
        self.config_name = config_name
        self.net = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.timeout.connect(self._close_server)
        self.server = None
        self.reply = self.probe = self.sink = self.output = None
        self.serial = 0
        self.active = self.paused = False
        self._last_error = ''
        self._state = QTextToSpeech.State.Ready
        self.warming = False
        self.pending_text = None
        self.overlay = None
        self.cfg = {}
        self.buffer = bytearray()
        self.segments = deque()
        self.records = []
        self.reload_after_configure()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        atexit.register(self._close_server)
        self.config_timer = QTimer(self)
        self.config_timer.setInterval(2000)
        self.config_timer.timeout.connect(self._check_settings)
        self.config_timer.start()
        QApplication.instance().aboutToQuit.connect(self.config_timer.stop)

    def _performance(self, event, *args):
        # Telemetry failure must never interrupt playback.
        try:
            if event == 'begin':
                if not self.cfg.get('performance_overlay', False):
                    return
                if self.overlay is None:
                    from calibre_plugins.audio_cpp_read_aloud.performance import PerformanceOverlay
                    self.overlay = PerformanceOverlay(self)
                self.overlay.begin()
            elif self.overlay is not None:
                if event in ('freeze', 'close'):
                    getattr(self.overlay, event)()
                elif self.overlay.running:
                    getattr(self.overlay.metrics, event)(*args)
        except Exception:
            if self.overlay is not None:
                self.overlay.close()

    @property
    def available_voices(self):
        if model_family(self.cfg) == 'ming3_tts':
            choices = [(PLUGIN_VOICE, 'Use plugin voice settings'),
                       (CLONED_VOICE, 'Cloned voice (reference recording)')]
            choices.extend((v, v) for v in self.cfg.get('voices', []))
            return {'': tuple(Voice(name=name, human_name=label,
                                   language_code=self.cfg.get('language', 'en'))
                              for name, label in choices)}
        return {'': tuple(Voice(name=v, language_code=self.cfg.get('language', 'en'),
                              human_name='Breeze voice (plugin settings)' if v == 'breeze' else v)
                          for v in (self.cfg.get('voices') or ['']))}

    def _state_to(self, state):
        if not self.warming and state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def reload_after_configure(self):
        self.shutdown()
        self.server = None
        try:
            self.cfg = self.preview_config if self.preview_config is not None else load_plugin_settings()
            if self.cfg.get('mode', 'managed') not in ('managed', 'external'):
                raise ValueError('mode must be managed or external')
            if not self.cfg.get('model'):
                raise ValueError('model is required')
            if not 8000 <= int(self.cfg.get('sample_rate', 24000)) <= 192000:
                raise ValueError('Invalid sample_rate')
            if int(self.cfg.get('channels', 1)) not in (1, 2):
                raise ValueError('channels must be 1 or 2')
            self.server = OwnedServer(self.cfg)
            self._last_error = ''
        except Exception as e:
            self._last_error = f'audio.cpp configuration: {e}'

    def _check_settings(self):
        if self.preview_config is not None:
            return
        if self.active:
            return
        try:
            updated = load_plugin_settings()
            if updated != self.cfg:
                self.reload_after_configure()
                if self.cfg.get('prewarm_on_open'):
                    self.prewarm()
        except Exception as error:
            self._last_error = 'Cannot apply audio.cpp settings: ' + str(error)

    def prewarm(self):
        if (not self.active and self.cfg.get('prewarm_on_open')
                and self.cfg.get('mode', 'managed') == 'managed'):
            self.say('Ready.', _warmup=True)

    def error_message(self):
        return self._last_error

    def say(self, text, _warmup=False):
        if self.warming and self.active and not _warmup:
            self.pending_text = text
            return
        self._clear()
        self._check_settings() if not _warmup else None
        # A settings reload may have initiated prewarming.
        if self.warming and self.active and not _warmup:
            self.pending_text = text
            return
        if self.server is None or self._last_error:
            self.reload_after_configure()
        self.warming = _warmup
        if self.server is None:
            self._fail(self._last_error)
            return
        try:
            self.settings = EngineSpecificSettings.create_from_config(self.engine_name, self.config_name)
            if self.preview_config is not None:
                self.settings = self.settings._replace(voice_name='', rate=0)
            for offset, sentence in split_into_sentences_for_tts(text, self.cfg.get('language', 'en')):
                # Bound long sentences without losing original text offsets.
                while sentence:
                    cut = min(len(sentence), 400)
                    if len(sentence) > cut:
                        cut = sentence.rfind(' ', 0, cut) + 1 or cut
                    part = sentence[:cut]
                    if part.strip():
                        self.segments.append((offset, part))
                    sentence, offset = sentence[cut:], offset + cut
            if not self.segments:
                self._state_to(QTextToSpeech.State.Ready)
                return
            self._performance('begin')
            self.url = self.server.start()
            self.ready = False
            self.deadline = time.monotonic() + float(self.cfg.get('startup_timeout_seconds', 120))
            self.next_probe = 0
            self.total = self.submitted = 0
            self.audio_rate = int(self.cfg.get('sample_rate', 24000))
            self.audio_channels = int(self.cfg.get('channels', 1))
            self.active = True
            self._last_error = ''
            # Calibre's manager expects Ready -> Speaking to begin a read session.
            self._state_to(QTextToSpeech.State.Speaking)
            self.timer.start()
            self._tick()
        except Exception as e:
            self._fail(str(e))

    def _request(self, suffix, timeout_ms):
        req = QNetworkRequest(QUrl(self.url + suffix))
        req.setTransferTimeout(timeout_ms)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        return req

    def _tick(self):
        if not self.active:
            return
        try:
            if self.server.process is not None and self.server.process.poll() is not None:
                raise RuntimeError('audio.cpp exited. See audiocpp-server.log for model/DLL errors.')
            if not self.ready:
                if time.monotonic() >= self.deadline:
                    raise TimeoutError('audio.cpp startup timed out; check the server log.')
                if self.probe is None and time.monotonic() >= self.next_probe:
                    serial = self.serial
                    probe = self.probe = self.net.get(self._request('/health', 2000))
                    probe.finished.connect(lambda: self._health(probe, serial))
                return
            if self.paused:
                return
            if self.warming:
                if self.reply is None and self.segments:
                    self._synthesize()
                elif self.reply is None and not self.segments:
                    pending = self.pending_text
                    self.pending_text = None
                    self.active = self.warming = False
                    self.timer.stop()
                    self._performance('freeze')
                    self._arm_idle()
                    if pending is not None:
                        self.say(pending)
                return
            if self.buffer and self.sink is None:
                self._make_sink()
            if self.sink is not None:
                frame = self.audio_channels * 2
                count = min(len(self.buffer), self.sink.bytesFree()) // frame * frame
                if count:
                    wrote = self.output.write(bytes(self.buffer[:count]))
                    if wrote < 0:
                        raise RuntimeError('Audio output write failed')
                    del self.buffer[:wrote]
                    self.submitted += wrote
                if self.sink.error() not in (QAudio.Error.NoError, QAudio.Error.UnderrunError):
                    raise RuntimeError(f'Audio output error: {self.sink.error()}')
                played = min(self.submitted, int(self.sink.processedUSecs() * self.bytes_per_second / 1000000))
                if self.sink.state() == QAudio.State.IdleState and not self.buffer:
                    played = self.submitted
            else:
                played = 0
            for rec in self.records:
                if not rec['marked'] and played >= rec['start'] and self.submitted > rec['start']:
                    rec['marked'] = True
                    self.saying.emit(rec['offset'], rec['length'])
            self.records = [r for r in self.records if r['end'] is None or r['end'] > played]
            # At most the current segment and one following segment are generated.
            if self.reply is None and self.segments and len(self.records) < 2:
                self._synthesize()
            if (not self.segments and self.reply is None and not self.buffer
                    and self.sink is not None and self.sink.state() == QAudio.State.IdleState):
                self.active = False
                self._performance('freeze')
                self.timer.stop()
                self._arm_idle()
                self._state_to(QTextToSpeech.State.Ready)
        except Exception as e:
            self._fail(str(e))

    def _health(self, reply, serial):
        if serial == self.serial and reply is self.probe:
            self.probe = None
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            self.ready = status == 200
            if self.ready:
                self._performance('health')
            self.next_probe = time.monotonic() + 0.5
        reply.deleteLater()

    def _make_sink(self):
        fmt = QAudioFormat()
        rate, channels = self.audio_rate, self.audio_channels
        fmt.setSampleRate(rate)
        fmt.setChannelCount(channels)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.bytes_per_second = rate * channels * 2
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull() or not device.isFormatSupported(fmt):
            raise RuntimeError('Default audio device does not support this model PCM format')
        self.sink = QAudioSink(device, fmt, self)
        self.sink.setVolume(self.settings.volume if self.settings.volume is not None else 1.0)
        self.sink.setBufferSize(self.bytes_per_second // 5)
        self.output = self.sink.start()
        if self.output is None:
            raise RuntimeError('Cannot open the default audio output')

    def _synthesize(self):
        offset, text = self.segments.popleft()
        rec = dict(start=self.total, end=None, offset=offset, length=len(text), marked=False)
        self.records.append(rec)
        body = speech_request(self.cfg, text, self.settings.voice_name, self.settings.rate)
        req = self._request('/v1/audio/speech', int(self.cfg.get('request_timeout_seconds', 300) * 1000))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        streaming = body.get('stream_format') == 'sse'
        req.setRawHeader(b'Accept', b'text/event-stream' if streaming else b'audio/wav')
        self._performance('request')
        reply = self.reply = self.net.post(req, json.dumps(body).encode('utf-8'))
        reply.setReadBufferSize(1024 * 1024)
        parser, serial = (SpeechEvents() if streaming else WaveResponse()), self.serial
        reply.readyRead.connect(lambda: self._data(reply, parser, serial))
        reply.finished.connect(lambda: self._finished(reply, parser, serial, rec))

    def _data(self, reply, parser, serial):
        if serial != self.serial or reply is not self.reply:
            return
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status != 200:
                return  # Preserve the response for the error report.
            content_type = bytes(reply.rawHeader(b'Content-Type')).lower()
            if isinstance(parser, WaveResponse):
                if not any(t in content_type for t in (b'audio/wav', b'audio/x-wav', b'audio/wave', b'application/octet-stream')):
                    raise ValueError('Expected WAV audio; check the model mode and server response')
            elif b'text/event-stream' not in content_type:
                raise ValueError('Expected SSE audio; check model mode=streaming and server version')
            for pcm in parser.feed(bytes(reply.readAll())):
                self._performance('chunk', len(pcm))
                if not self.warming:
                    self.buffer.extend(pcm)
                self.total += len(pcm)
                if len(self.buffer) > 16 * 1024 * 1024:
                    raise ValueError('Audio buffer limit reached; shorten text chunks or resume playback')
        except Exception as e:
            self._fail(str(e))

    def _finished(self, reply, parser, serial, rec):
        if serial == self.serial and reply is self.reply:
            self._data(reply, parser, serial)
            if serial == self.serial:
                try:
                    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                    if status != 200 or reply.error().value != 0:
                        detail = bytes(reply.readAll()).decode('utf-8', errors='replace')[:2000]
                        raise RuntimeError(f'HTTP {status}: {reply.errorString()} {detail}')
                    if isinstance(parser, WaveResponse):
                        pcm, rate, channels = parser.finish()
                        if rec['start'] and (rate, channels) != (self.audio_rate, self.audio_channels):
                            raise ValueError('Model changed its WAV format during playback')
                        self.audio_rate, self.audio_channels = rate, channels
                        self._performance('chunk', len(pcm))
                        if not self.warming:
                            if len(self.buffer) + len(pcm) > 16 * 1024 * 1024:
                                raise ValueError('Audio buffer limit reached')
                            self.buffer.extend(pcm)
                        self.total += len(pcm)
                    else:
                        parser.finish()
                    if self.total == rec['start']:
                        raise ValueError('The server returned no audio')
                    if (self.total - rec['start']) % (self.audio_channels * 2):
                        raise ValueError('Incomplete PCM frame in server response')
                    self._performance('finish')
                    rec['end'] = self.total
                    self.reply = None
                except Exception as e:
                    self._fail(str(e))
        reply.deleteLater()

    def pause(self):
        if self.active:
            self.paused = True
            if self.sink is not None:
                self.sink.suspend()
            self._state_to(QTextToSpeech.State.Paused)

    def resume(self):
        if self.active and self.paused:
            self.paused = False
            if self.sink is not None:
                self.sink.resume()
            self._state_to(QTextToSpeech.State.Speaking)

    def _clear(self):
        self._performance('freeze')
        self.warming = False
        self.pending_text = None
        self.serial += 1  # Ignore signals from cancelled/older network requests.
        self.active = self.paused = False
        self.timer.stop()
        self.idle.stop()
        for attr in ('reply', 'probe'):
            reply = getattr(self, attr)
            setattr(self, attr, None)
            if reply is not None:
                reply.abort()
                reply.deleteLater()
        if self.sink is not None:
            self.sink.reset()
            self.sink.deleteLater()
            self.sink = self.output = None
        self.buffer.clear()
        self.segments.clear()
        self.records.clear()

    def _close_server(self):
        if self.server is not None:
            self.server.close()

    def _arm_idle(self):
        if self.cfg.get('keep_loaded_while_open'):
            return
        seconds = max(0, float(self.cfg.get('idle_shutdown_seconds', 60)))
        self.idle.start(min(2147483647, int(seconds * 1000)))

    def stop(self):
        self._clear()
        # Killing only an owned process also cancels GPU work reliably on stop/navigation.
        if not self.cfg.get('keep_loaded_while_open'):
            self._close_server()
        self._state_to(QTextToSpeech.State.Ready)
        self._check_settings()

    def shutdown(self):
        self._clear()
        self._performance('close')
        self._close_server()

    def _fail(self, message):
        self.shutdown()
        self._last_error = message
        self._state_to(QTextToSpeech.State.Error)
