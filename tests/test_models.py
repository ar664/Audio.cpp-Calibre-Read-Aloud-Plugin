import copy
import importlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import test_pronunciation as previous

core = previous.core
profiles = previous.profiles
catalog = importlib.import_module(previous.PACKAGE + '.model_catalog').CATALOG


def wav_bytes(rate=44100, channels=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b'\0\1' * 100 * channels)
    return out.getvalue()


class ModelTests(unittest.TestCase):
    def test_catalog_covers_local_gguf_tts_specs_and_new_families(self):
        for path in (previous.SOURCE / 'bin/model_specs').glob('*.json'):
            spec = json.loads(path.read_text(encoding='utf-8'))
            if 'tts' in spec.get('tasks', []) and any(s.get('format') == 'gguf' for s in spec.get('sources', [])):
                self.assertIn(spec['family'], catalog)
        for family in ('ming3_tts', 'ming3_audio', 'gradium_phonon', 'xtts_v2'):
            self.assertIn(family, catalog)
        for family in ('personaplex', 'qwen3_asr', 'stable_audio'):
            self.assertNotIn(family, catalog)

    def test_every_preset_can_build_an_offline_request_without_stale_voice(self):
        for family in catalog:
            with self.subTest(family=family):
                cfg = profiles.preset(family)
                body = core.speech_request(cfg, 'Hello.', 'heart', 0)
                self.assertEqual(body['response_format'], 'wav')
                self.assertNotIn('stream_format', body)
                self.assertEqual(cfg['server_settings']['models'][0]['family'], family)
                self.assertEqual(cfg['server_settings']['models'][0]['mode'], 'offline')
                if not cfg['voice']:
                    self.assertNotIn('voice', body)

    def test_profiles_preserve_paths_reference_options_and_shared_preferences(self):
        cfg = profiles.preset('kokoro')
        cfg.update(executable='server.exe', pronunciation_enabled=False)
        for family in ('magpie_tts', 'xtts_v2', 'qwen3_tts'):
            cfg = profiles.switch_profile(cfg, family)
            cfg['server_settings']['models'][0]['path'] = family + '.gguf'
            cfg['reference_audio'] = family + '.wav'
            cfg['options'] = {'seed': 12}
            other = profiles.switch_profile(cfg, 'breeze')
            restored = profiles.switch_profile(other, family)
            for key in profiles.PROFILE_KEYS:
                self.assertEqual(restored.get(key), cfg.get(key))
            self.assertEqual(restored['executable'], 'server.exe')
            self.assertFalse(restored['pronunciation_enabled'])

    def test_generic_reference_and_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ref.wav'
            path.write_bytes(wav_bytes())
            cfg = profiles.preset('qwen3_tts')
            cfg.update(breeze_voice_mode='reference', reference_audio=str(path),
                       reference_text='Original words', breeze_instruction='Calm voice')
            body = core.speech_request(cfg, 'Next sentence')
            self.assertEqual(body['voice_ref']['path'], str(path.resolve()))
            self.assertEqual(body['reference_text'], 'Original words')
            self.assertNotIn('voice', body)
            self.assertEqual(body['options']['instruct'], 'Calm voice')
            path.unlink()
            with self.assertRaises(ValueError):
                core.speech_request(cfg, 'Missing reference')

    def test_wav_formats_fragmentation_and_truncation(self):
        for rate in (16000, 22050, 24000, 44100, 48000):
            for channels in (1, 2):
                data = wav_bytes(rate, channels)
                parser = core.WaveResponse()
                for byte in data:
                    self.assertEqual(parser.feed(bytes([byte])), [])
                pcm, actual_rate, actual_channels = parser.finish()
                self.assertEqual((actual_rate, actual_channels), (rate, channels))
                self.assertEqual(pcm, b'\0\1' * 100 * channels)
                with self.assertRaises(ValueError):
                    core.decode_wav(data[:-1])
        with self.assertRaises((ValueError, wave.Error, EOFError)):
            core.decode_wav(b'not audio')
        parser = core.WaveResponse()
        with self.assertRaises(ValueError):
            parser.feed(b'\0' * (16 * 1024 * 1024 + 1))


class MingTests(unittest.TestCase):
    def test_long_reference_uses_speaker_identity_without_changing_saved_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            ref = Path(directory) / 'stereo.wav'
            with wave.open(str(ref), 'wb') as wav:
                wav.setparams((2,2,48000,0,'NONE','not compressed'))
                wav.writeframes(b'\0\1' * 2 * 48000 * 11)
            original = ref.read_bytes()
            cfg = profiles.preset('ming3_tts')
            cfg.update(breeze_voice_mode='reference', reference_audio=str(ref),
                       reference_text='The exact reference transcript.')
            cfg['options']['reference_text'] = 'Transcript in Advanced options.'
            body = core.speech_request(cfg, 'Hello.')
            self.assertEqual(body['voice_ref']['path'], str(ref.resolve()))
            self.assertEqual(ref.read_bytes(), original)
            self.assertNotIn('reference_text', body)
            self.assertNotIn('reference_text', body['options'])
            self.assertEqual(cfg['reference_text'], 'The exact reference transcript.')
            self.assertIn('reference_text', cfg['options'])
            # Replacing the file with a short recording immediately restores
            # acoustic conditioning; duration decisions must not be cached.
            ref.write_bytes(wav_bytes(48000, 2))
            short = core.speech_request(cfg, 'Hello.')
            self.assertEqual(short['reference_text'], cfg['reference_text'])

    def test_placeholder_profiles_upgrade_without_losing_user_configuration(self):
        old = profiles.preset('ming3_tts')
        old.update(sample_rate=24000, voices=[], supports_speed=True)
        old['server_settings']['models'][0]['path'] = 'my-ming.gguf'
        old['options'] = {'seed': 42}
        saved = profiles.switch_profile(old, 'kokoro')
        restored = profiles.switch_profile(saved, 'ming3_tts')
        self.assertEqual(restored['sample_rate'], 44100)
        self.assertFalse(restored['supports_speed'])
        self.assertEqual(len(restored['voices']), 4)
        self.assertEqual(restored['options'], {'seed': 42})
        self.assertEqual(restored['server_settings']['models'][0]['path'], 'my-ming.gguf')
        settings = importlib.import_module(previous.PACKAGE + '.settings')
        old['model_profiles'] = {'ming3_tts': copy.deepcopy(old)}
        with patch.object(settings, 'JSONConfig', return_value=old):
            loaded = settings.load()
        self.assertEqual(loaded['sample_rate'], 44100)
        self.assertEqual(loaded['model_profiles']['ming3_tts']['sample_rate'], 44100)

    def test_format_voices_and_conditioning_templates(self):
        cfg = profiles.preset('ming3_tts')
        self.assertEqual((cfg['sample_rate'], cfg['channels']), (44100, 1))
        self.assertFalse(cfg['supports_speed'])
        self.assertEqual(catalog['ming3_tts']['modes'], ['offline', 'streaming'])
        self.assertEqual(cfg['voices'], ['US_Emma', 'US_James', 'UK_George', 'UK_Charlotte'])
        for voice in ['', *cfg['voices']]:
            with self.subTest(voice=voice):
                body = core.speech_request(cfg, 'Hello.', voice, rate=2)
                self.assertNotIn('voice', body)
                self.assertNotIn('speed', body['options'])
                self.assertEqual(body['options']['template_name'], 'ip' if voice else 'tts')
                if voice:
                    self.assertEqual(body['options']['voice_id'], voice)
        cfg['breeze_instruction'] = 'A calm adult narrator.'
        body = core.speech_request(cfg, 'Hello.', core.PLUGIN_VOICE)
        self.assertEqual(body['options']['template_name'], 'voice_design')
        self.assertNotIn('voice_id', body['options'])

    def test_reference_overrides_saved_voice_and_keeps_optional_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            ref = Path(directory) / 'ref.wav'
            ref.write_bytes(wav_bytes())
            cfg = profiles.preset('ming3_tts')
            cfg.update(breeze_voice_mode='reference', reference_audio=str(ref))
            for transcript in ('', 'Words in the recording.'):
                cfg['reference_text'] = transcript
                body = core.speech_request(cfg, 'Hello.', core.PLUGIN_VOICE)
                self.assertEqual(body['options']['template_name'], 'tts')
                self.assertNotIn('voice_id', body['options'])
                self.assertNotIn('voice', body)
                self.assertEqual(body['voice_ref']['path'], str(ref.resolve()))
                self.assertEqual(body.get('reference_text', ''), transcript)

    def test_explicit_controls_and_streaming_format(self):
        cfg = profiles.preset('ming3_tts')
        cfg['server_settings']['models'][0]['mode'] = 'streaming'
        cfg['supports_speed'] = True  # An old preference must not send numeric speed.
        cfg['options'] = {'template_name': 'basic', 'speed': '\u4e2d\u901f', 'pitch': '\u4e2d'}
        body = core.speech_request(cfg, 'Hello.', core.PLUGIN_VOICE, rate=2)
        self.assertEqual(body['response_format'], 'pcm')
        self.assertEqual(body['stream_format'], 'sse')
        self.assertEqual(body['options']['speed'], '\u4e2d\u901f')
        self.assertEqual(body['options']['template_name'], 'basic')
        self.assertNotIn('voice_id', body['options'])


    def test_viewer_clone_and_native_choices_override_saved_conditioning(self):
        with tempfile.TemporaryDirectory() as directory:
            ref = Path(directory) / 'ref.wav'
            ref.write_bytes(wav_bytes())
            cfg = profiles.preset('ming3_tts')
            cfg.update(reference_audio=str(ref), reference_text='Reference words',
                       breeze_instruction='A calm voice')
            cfg['options'].update(template_name='voice_design', voice_id='US_James')
            original = copy.deepcopy(cfg)
            clone = core.speech_request(cfg, 'Hello.', core.CLONED_VOICE)
            self.assertIn('voice_ref', clone)
            self.assertEqual(clone['options']['template_name'], 'tts')
            self.assertNotIn('voice_id', clone['options'])
            self.assertEqual(cfg, original)
            cfg['breeze_voice_mode'] = 'reference'
            native = core.speech_request(cfg, 'Hello.', 'UK_George')
            self.assertNotIn('voice_ref', native)
            self.assertNotIn('reference_text', native)
            self.assertNotIn('instruct', native['options'])
            self.assertEqual(native['options']['voice_id'], 'UK_George')
            self.assertEqual(native['options']['template_name'], 'ip')
            self.assertEqual(cfg['breeze_voice_mode'], 'reference')
            ref.unlink()
            with self.assertRaisesRegex(ValueError, 'Voice conditioning'):
                core.speech_request(cfg, 'Hello.', core.CLONED_VOICE)
            self.assertNotIn('voice_ref', core.speech_request(cfg, 'Hello.', 'US_Emma'))


class ModelWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous.WidgetTests.setUpClass()

    def test_all_picker_entries_and_package_directory(self):
        widget = previous.WidgetTests.config.SettingsWidget()
        try:
            self.assertEqual(widget.preset_choice.count(), len(catalog))
            with tempfile.TemporaryDirectory() as directory:
                exe = Path(directory) / 'server.exe'
                exe.touch()
                for family in ('magpie_tts', 'pocket_tts', 'xtts_v2'):
                    cfg = profiles.preset(family)
                    cfg.update(mode='managed', executable=str(exe))
                    cfg['server_settings']['models'][0]['path'] = directory
                    widget._populate(cfg)
                    widget._ownership_changed()
                    saved = widget.collect()
                    self.assertEqual(saved['server_settings']['models'][0]['path'], str(Path(directory).resolve()))
                    self.assertEqual(saved['profile'], family)
                    self.assertTrue(widget.breeze_tab.isEnabled())
        finally:
            widget.close()


class OfflineBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_lifecycle import LifecycleTests
        LifecycleTests.setUpClass()
        cls.app = LifecycleTests.app
        cls.backend = LifecycleTests.backend

    def test_real_qt_http_offline_warmup_detects_format_and_reuses_server(self):
        bodies = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
            def do_POST(self):
                bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.end_headers()
                self.wfile.write(wav_bytes(48000, 2))
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        cfg = copy.deepcopy(previous.WidgetTests.settings.DEFAULTS)
        cfg.update(profiles.preset('magpie_tts'))
        cfg.update(prewarm_on_open=True, keep_loaded_while_open=True)
        class Server:
            process = None
            def __init__(self, config):
                self.closed = 0
            def start(self):
                return f'http://127.0.0.1:{http.server_port}'
            def close(self):
                self.closed += 1
        backend = None
        try:
            with patch.object(self.backend, 'OwnedServer', Server), patch.object(self.backend, 'load_plugin_settings', return_value=cfg):
                backend = self.backend.AudioCpp(parent=self.app)
                for _ in range(2):
                    backend.prewarm()
                    deadline = time.monotonic() + 3
                    while backend.active and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertFalse(backend.active)
                    self.assertEqual(backend.error_message(), '')
                    self.assertEqual((backend.audio_rate, backend.audio_channels), (48000, 2))
                    self.assertEqual(backend.total, 400)
                    self.assertIsNone(backend.sink)
                    self.assertEqual(backend.server.closed, 0)
                self.assertEqual(len(bodies), 2)
                self.assertEqual(bodies[0]['response_format'], 'wav')
                self.assertNotIn('stream_format', bodies[0])
                formats, written, highlights = [], [], []
                def make_sink():
                    formats.append((backend.audio_rate, backend.audio_channels))
                    backend.bytes_per_second = backend.audio_rate * backend.audio_channels * 2
                    backend.sink = Mock()
                    backend.sink.bytesFree.return_value = 1000000
                    backend.sink.error.return_value = self.backend.QAudio.Error.NoError
                    backend.sink.state.return_value = self.backend.QAudio.State.IdleState
                    backend.sink.processedUSecs.return_value = 1000000
                    backend.output = Mock()
                    backend.output.write.side_effect = lambda data: written.append(data) or len(data)
                backend.saying.connect(lambda *args: highlights.append(args))
                with patch.object(backend, '_make_sink', side_effect=make_sink):
                    backend.say('Read this sentence.')
                    deadline = time.monotonic() + 3
                    while backend.active and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                self.assertEqual(backend.error_message(), '')
                self.assertFalse(backend.active)
                self.assertEqual(formats, [(48000, 2)])
                self.assertEqual(b''.join(written), b'\0\1' * 200)
                self.assertEqual(highlights, [(0, len('Read this sentence.'))])
        finally:
            if backend:
                backend.shutdown()
                backend.config_timer.stop()
            http.shutdown()
            http.server_close()
