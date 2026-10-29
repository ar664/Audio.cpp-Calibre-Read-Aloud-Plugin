"""Pure-Python transport helpers and owned server lifecycle. GPL-3.0-or-later."""
import base64
import ctypes
import json
import io
import os
import re
from functools import lru_cache
import socket
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlsplit


def model_family(config):
    for model in config.get('server_settings', {}).get('models', []):
        if model.get('id') == config.get('model'):
            return model.get('family', '')
    profile = config.get('profile', '')
    return {'breeze': 'breeze_tts', 'kokoro': 'kokoro_tts'}.get(profile, profile)


def streaming_model(config):
    for model in config.get('server_settings', {}).get('models', []):
        if model.get('id') == config.get('model'):
            return model.get('mode', 'offline') == 'streaming'
    # Preserve external-server settings from versions before the model catalog.
    return config.get('profile', 'kokoro') in ('kokoro', 'breeze')


def decode_wav(data):
    """Decode bounded PCM16 WAV responses without guessing the model's rate."""
    with wave.open(io.BytesIO(data), 'rb') as wav:
        channels, rate = wav.getnchannels(), wav.getframerate()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or not 8000 <= rate <= 192000:
            raise ValueError('Expected 16-bit PCM WAV, mono/stereo, 8000–192000 Hz')
        pcm = wav.readframes(wav.getnframes())
        if len(pcm) != wav.getnframes() * channels * 2:
            raise ValueError('Truncated WAV response')
    return pcm, rate, channels


class WaveResponse:
    """Bound one offline sentence response; never play WAV headers as PCM."""
    def __init__(self):
        self.data = bytearray()

    def feed(self, data):
        if len(self.data) + len(data) > 16 * 1024 * 1024:
            raise ValueError('WAV response exceeds the 16 MiB segment limit')
        self.data.extend(data)
        return []

    def finish(self):
        return decode_wav(self.data)


def pronunciation_entries(config):
    """Validate literal replacements; empty dictionaries preserve old behavior."""
    entries = config.get('pronunciations', [])
    if not isinstance(entries, list):
        raise ValueError('Pronunciations must be a list')
    sensitive = bool(config.get('pronunciation_case_sensitive', False))
    seen, result = set(), []
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f'Pronunciation row {number} is invalid')
        term, replacement = entry.get('text', ''), entry.get('replacement', '')
        if not isinstance(term, str) or not isinstance(replacement, str):
            raise ValueError(f'Pronunciation row {number} must contain text')
        term, replacement = term.strip(), replacement.strip()
        if not term or not replacement:
            raise ValueError(f'Pronunciation row {number} needs both Written text and Say as')
        key = term if sensitive else term.casefold()
        if key in seen:
            raise ValueError(f'Duplicate pronunciation: {term}')
        seen.add(key)
        result.append((term, replacement))
    return tuple(result)


@lru_cache(maxsize=8)
def _pronunciation_pattern(entries, sensitive):
    # Longest phrase wins. Capturing groups select the replacement without
    # case-folding matched text (which can differ under Unicode regex rules).
    entries = sorted(entries, key=lambda entry: len(entry[0]), reverse=True)
    pattern = r'(?<!\w)(?:' + '|'.join('(' + re.escape(t) + ')' for t, _ in entries) + r')(?!\w)'
    return re.compile(pattern, 0 if sensitive else re.IGNORECASE), tuple(r for _, r in entries)


def apply_pronunciations(text, config):
    if not config.get('pronunciation_enabled', True):
        return text
    entries = pronunciation_entries(config)
    if not entries:
        return text
    pattern, replacements = _pronunciation_pattern(entries, bool(config.get('pronunciation_case_sensitive', False)))
    # One pass: replacement text is never processed again, including backslashes.
    return pattern.sub(lambda match: replacements[match.lastindex - 1], text)


MING_ACOUSTIC_REFERENCE_SECONDS = 10
CLONED_VOICE = '__audio_cpp_cloned_voice__'
PLUGIN_VOICE = '__audio_cpp_plugin_voice__'


def ming_acoustic_reference_supported(source):
    """Use a conservative acoustic-prompt budget for audio.cpp 0.9.3.

    The 24.25-second sample plus transcript reproducibly degraded to silence
    or unintelligible speech in both Q8 and BF16. Speaker-only conditioning
    works with the full recording; short acoustic references also work.
    """
    try:
        with wave.open(str(source), 'rb') as wav:
            return 0 < wav.getnframes() <= wav.getframerate() * MING_ACOUSTIC_REFERENCE_SECONDS
    except (wave.Error, EOFError):
        # Leave decoding of other WAV encodings to audio.cpp, using the safer
        # speaker-only route when Python cannot inspect their duration.
        return False


def speech_request(config, text, voice_name='', rate=0):
    """Keep model-specific options and stale Calibre voice preferences separate."""
    if model_family(config) == 'ming3_tts':
        # Viewer choices override conditioning for this request only.
        if voice_name == CLONED_VOICE or voice_name in config.get('voices', []):
            config = dict(config, options=dict(config.get('options', {})))
            cloning = voice_name == CLONED_VOICE
            config['breeze_voice_mode'] = 'reference' if cloning else 'design'
            config['breeze_instruction'] = ''
            for key in ('instruct', 'voice_id', 'reference_text', 'template_name'):
                config['options'].pop(key, None)
            config['options']['template_name'] = 'tts' if cloning else 'ip'
            if cloning and not Path(config.get('reference_audio') or '').is_file():
                raise ValueError('Set a reference WAV in the plugin settings under Voice conditioning, then select Cloned voice again.')
    body = dict(model=config['model'], input=apply_pronunciations(text, config), response_format='pcm', stream_format='sse')
    if not streaming_model(config):
        body['response_format'] = 'wav'
        body.pop('stream_format')
    options = dict(config.get('options', {}))
    if model_family(config) == 'breeze_tts':
        # Kokoro's saved voice/speed must never leak into a Breeze request.
        for key in ('speed', 'voice_id', 'instruction', 'reference_text'):
            options.pop(key, None)
        options['instruct'] = config.get('breeze_instruction', '').strip() or 'Speak clearly and naturally.'
        mode = config.get('breeze_voice_mode', 'design')
        if mode == 'reference':
            audio = config.get('reference_audio', '').strip()
            transcript = config.get('reference_text', '').strip()
            if not audio or not transcript:
                raise ValueError('Breeze reference mode requires a WAV recording and its exact transcript')
            if not Path(audio).is_file():
                raise ValueError('Breeze reference WAV no longer exists: ' + audio)
            body['voice_ref'] = {'type': 'path', 'path': str(Path(audio).resolve())}
            body['reference_text'] = transcript
        elif mode != 'design':
            raise ValueError('Unknown Breeze voice mode: ' + mode)
    else:
        # After a preset switch, ignore a voice saved for a different model.
        available = config.get('voices', [])
        voice = voice_name if voice_name in available else config.get('voice', '')
        if voice:
            body['voice'] = voice
        if config.get('supports_speed', True) and model_family(config) != 'ming3_tts':
            options['speed'] = 2 ** rate
        if model_family(config) not in ('', 'kokoro_tts'):
            from calibre_plugins.audio_cpp_read_aloud.model_catalog import CATALOG
            params = {p['name']: p for p in CATALOG.get(model_family(config), {}).get('options', {}).get('request', [])}
            if 'language' in params and config.get('language'):
                options.setdefault('language', config['language'])
            instruction = config.get('breeze_instruction', '').strip()
            key = next((k for k in ('instruct', 'instruction', 'voice_description', 'description') if k in params), None)
            if instruction and key:
                options[key] = instruction
            if config.get('breeze_voice_mode') == 'reference':
                audio = config.get('reference_audio', '').strip()
                if not audio or not Path(audio).is_file():
                    raise ValueError('Choose an existing reference WAV for this model')
                body.pop('voice', None)
                body['voice_ref'] = {'type': 'path', 'path': str(Path(audio).resolve())}
                if config.get('reference_text', '').strip():
                    body['reference_text'] = config['reference_text'].strip()
    if model_family(config) == 'kokoro_tts' and body.get('voice'):
        from calibre_plugins.audio_cpp_read_aloud.model_catalog import CATALOG
        if body['voice'] in CATALOG['kokoro_tts'].get('voices', []):
            options['voice_id'] = body.pop('voice')
    if model_family(config) == 'ming3_tts':
        if 'voice_ref' in body and not ming_acoustic_reference_supported(body['voice_ref']['path']):
            body.pop('reference_text', None)
            options.pop('reference_text', None)
        # Ming's named voices are IP-template controls, not server voice presets.
        voice = body.pop('voice', '')
        if not options.get('template_name'):
            if 'voice_ref' in body:
                options['template_name'] = 'tts'
            elif options.get('instruct'):
                options['template_name'] = 'voice_design'
            elif voice or options.get('voice_id'):
                options['template_name'] = 'ip'
            else:
                options['template_name'] = 'tts'
        if options['template_name'] == 'ip' and voice and 'voice_ref' not in body:
            options.setdefault('voice_id', voice)
    if options:
        body['options'] = options
    return body


class SpeechEvents:
    """Incremental SSE decoder; handles network splits, CRLF and error events."""
    def __init__(self):
        self.pending = b''
        self.lines = []
        self.done = False
        self.audio_done = False

    def feed(self, data):
        self.pending += data
        chunks = []
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if line.startswith(b'data:'):
                self.lines.append(line[5:].lstrip(b' '))
            elif not line and self.lines:
                body = b'\n'.join(self.lines)
                self.lines.clear()
                if body == b'[DONE]':
                    self.done = True
                    continue
                event = json.loads(body)
                kind = event.get('type', '')
                if kind == 'speech.audio.delta':
                    if self.done or self.audio_done:
                        raise ValueError('Audio received after end of stream')
                    chunks.append(base64.b64decode(event['audio'], validate=True))
                elif kind == 'speech.audio.done':
                    self.audio_done = True
                elif kind == 'error' or 'error' in event:
                    raise ValueError(str(event.get('error', event.get('message', event)))[:2000])
            if len(self.pending) + sum(map(len, self.lines)) > 8 * 1024 * 1024:
                raise ValueError('Oversized SSE event')
        if len(self.pending) > 8 * 1024 * 1024:
            raise ValueError('Oversized SSE line')
        return chunks

    def finish(self):
        if not (self.done and self.audio_done) or self.pending.strip() or self.lines:
            raise ValueError('Speech stream ended before its completion markers')


def local_url(value):
    u = urlsplit(value)
    if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('This prototype accepts only a local HTTP server')
    if u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
        raise ValueError('Use a base URL such as http://127.0.0.1:8080')
    return value.rstrip('/')


class WindowsJob:
    """Non-inheritable kill-on-close job; no process-name-based termination."""
    def __init__(self, pid):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', w.DWORD), ('MinWS', ctypes.c_size_t), ('MaxWS', ctypes.c_size_t),
                        ('Active', w.DWORD), ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('ro', 'wo', 'oo', 'rt', 'wt', 'ot')]
        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]
        k = self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.SetInformationJobObject.restype = w.BOOL
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.AssignProcessToJobObject.restype = w.BOOL
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = Extended()
            info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = k.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not k.AssignProcessToJobObject(self.handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                k.CloseHandle(process)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def resolve_mio_packages(settings, working):
    """Resolve MioTTS package and codec paths in the private server config."""
    for model in settings.get('models', []):
        if model.get('family') != 'miotts':
            continue
        path = Path(model.get('path', '')).expanduser()
        if not path.is_absolute():
            path = Path(working) / path
        folder = path if path.is_dir() else path.parent
        if path.is_dir():
            weights = list(path.glob('*.gguf'))
            if len(weights) != 1:
                raise ValueError('MioTTS package must contain one GGUF; select the desired GGUF file when there are several.')
            model['path'] = str(weights[0].resolve())
        options = model.setdefault('session_options', {})
        key = 'miotts.codec_model_path'
        gguf_folders = [folder / 'MioCodec-25Hz-44.1kHz-v2-GGUF', folder.parent / 'MioCodec-25Hz-44.1kHz-v2-GGUF']
        if options.get(key):
            codec = Path(options[key]).expanduser()
            if not codec.is_absolute():
                codec = folder / codec
        else:
            candidates = gguf_folders + [folder / 'MioCodec-25Hz-44.1kHz-v2', folder.parent / 'MioCodec-25Hz-44.1kHz-v2']
            codec = next((p for p in candidates if p.is_dir()), candidates[0])
        # Upgrade the known legacy raw-checkpoint layout when its GGUF replacement exists.
        if codec.name == 'MioCodec-25Hz-44.1kHz-v2' and codec.is_dir() and not list(codec.glob('*.gguf')):
            codec = next((p for p in gguf_folders if list(p.glob('*.gguf'))), codec)
        if codec.is_dir():
            weights = list(codec.glob('*.gguf'))
            if len(weights) != 1:
                raise ValueError('Choose a MioCodec GGUF file in miotts.codec_model_path. The codec directory must contain exactly one GGUF; raw safetensors checkpoints produced incorrect speech with audio.cpp 0.9.3.')
            codec = weights[0]
        if not codec.is_file() or codec.suffix.lower() != '.gguf':
            raise ValueError('MioCodec GGUF not found. Place MioCodec-25Hz-44.1kHz-v2-GGUF inside or beside the MioTTS package, or set miotts.codec_model_path to its GGUF file.')
        options[key] = str(codec.resolve())


class OwnedServer:
    def __init__(self, config):
        self.config = config
        self.process = self.job = self.temp = self.log = None
        self.url = ''
        self.release_instance = None

    def start(self):
        if self.config.get('mode', 'managed') == 'external':
            self.url = local_url(self.config['base_url'])
            return self.url
        if self.process is not None and self.process.poll() is None:
            return self.url
        self.close()
        from calibre.utils.lock import create_single_instance_mutex
        self.release_instance = create_single_instance_mutex('audio-cpp-read-aloud-server')
        if self.release_instance is None:
            raise RuntimeError('audio.cpp is already owned by another ebook viewer. '
                               'Stop reading there (or close that viewer when Keep loaded is enabled), '
                               'then press Play here. No second server was started.')
        try:
            return self._launch()
        except Exception:
            self.close()
            raise

    def _launch(self):
        exe = Path(self.config['executable']).expanduser().resolve(strict=True)
        if 'server_settings' in self.config:
            settings = json.loads(json.dumps(self.config['server_settings']))
            working = Path(self.config.get('working_directory') or exe.parent).resolve(strict=True)
        else:
            source = Path(self.config['server_config']).expanduser().resolve(strict=True)
            settings = json.loads(source.read_text(encoding='utf-8-sig'))
            working = source.parent
        resolve_mio_packages(settings, working)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        # A private port avoids stealing an independently running server.
        settings.update(host='127.0.0.1', port=port, ui=False, ui_management=False)
        self.temp = tempfile.TemporaryDirectory(prefix='calibre-audiocpp-')
        runtime = Path(self.temp.name) / 'server.json'
        runtime.write_text(json.dumps(settings), encoding='utf-8')
        log_path = Path(self.config.get('log_file', str(working / 'audiocpp-server.log')))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open('ab', buffering=0)
        try:
            environment = os.environ.copy()
            for setting, variable in (('espeak_library', 'AUDIOCPP_ESPEAK_LIBRARY'), ('espeak_data', 'AUDIOCPP_ESPEAK_DATA')):
                if self.config.get(setting):
                    environment[variable] = self.config[setting]
            self.process = subprocess.Popen(
                [str(exe), '--config', str(runtime), '--host', '127.0.0.1', '--port', str(port), '--no-ui'],
                cwd=str(working), env=environment, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if os.name == 'nt':
                self.job = WindowsJob(self.process.pid)
        except Exception:
            self.close()
            raise
        self.url = f'http://127.0.0.1:{port}'
        return self.url

    def close(self):
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                raise RuntimeError('audio.cpp did not exit; retaining the single-server lock')
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None
        if self.release_instance is not None:
            self.release_instance()
            self.release_instance = None
