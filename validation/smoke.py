"""Run with calibre-debug -e in an isolated CALIBRE_CONFIG_DIRECTORY."""
import base64
import json
import os
from pathlib import Path
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation'
for path in ROOT.glob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')
print('PASS: all seven plugin modules compile', flush=True)
archive = OUT / 'audio-cpp-read-aloud-0.1.0.zip'
with zipfile.ZipFile(archive, 'w') as z:
    for path in ROOT.iterdir():
        if path.suffix == '.py' or path.name.startswith('plugin-import-name-'):
            z.write(path, path.name)

from calibre.customize.zipplugin import loader
cls = loader.load(str(archive))
plugin = cls(str(archive))
plugin.initialize()
from qt.core import QApplication, QMediaDevices, QTextToSpeech
app = QApplication([])
from calibre.gui2.tts import types
assert 'audiocpp_plugin' in types.available_engines()
plugin.initialize()
assert list(types.available_engines()).count('audiocpp_plugin') == 1
print('PASS: workspace ZIP imports and registers in real Calibre; version', plugin.version, flush=True)

from calibre_plugins.audio_cpp_read_aloud.core import SpeechEvents
pcm = b'\x00\x01' * 20
stream = ('data: ' + json.dumps({'type': 'speech.audio.delta', 'audio': base64.b64encode(pcm).decode()}) + '\r\n\r\n'
          'data: {"type":"speech.audio.done"}\n\n' 'data: [DONE]\n\n').encode()
for split in range(len(stream) + 1):
    parser = SpeechEvents()
    decoded = parser.feed(stream[:split]) + parser.feed(stream[split:])
    parser.finish()
    assert b''.join(decoded) == pcm
parser = SpeechEvents()
try:
    parser.finish()
except ValueError:
    pass
else:
    raise AssertionError('Truncated stream accepted')
print('PASS: SSE split boundaries and truncated stream rejection', flush=True)

from calibre_plugins.audio_cpp_read_aloud import settings
saved = json.loads((Path(os.environ['APPDATA']) / 'calibre/plugins/audio_cpp_read_aloud.json').read_text(encoding='utf-8'))
cfg = dict(settings.DEFAULTS)
cfg.update(saved)
cfg.update(saved['model_profiles']['kokoro'])
cfg['idle_shutdown_seconds'] = 1
cfg['log_file'] = str(OUT / 'server.log')
settings.save(cfg)
from calibre_plugins.audio_cpp_read_aloud.config import SettingsWidget
widget = SettingsWidget()
print('PASS: settings widget constructs', flush=True)
backend = types.create_tts_backend('audiocpp_plugin')
assert not backend.error_message(), backend.error_message()
assert backend.server.process is None
print('AUDIO DEVICE:', QMediaDevices.defaultAudioOutput().description(), flush=True)

def until(condition, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if backend.error_message():
            raise AssertionError(backend.error_message())
        if condition():
            return
        time.sleep(.01)
    raise AssertionError('Timeout waiting for playback condition')

try:
    backend.say('This is a test of the Calibre audio plugin. Reading aloud is working.')
    process = backend.server.process
    assert process is not None
    assert backend.server.job is not None
    until(lambda: backend.submitted > 0)
    print('PASS: real CUDA Kokoro synthesis streams PCM to Windows audio output', flush=True)
    backend.pause()
    assert backend.paused and process.poll() is None
    backend.resume()
    assert not backend.paused
    until(lambda: not backend.active)
    print('PASS: pause/resume and playback completion; PCM bytes', backend.total, flush=True)
    until(lambda: process.poll() is not None, 10)
    print('PASS: idle shutdown kills owned server', flush=True)
    backend.say('Testing stop and restart.')
    second = backend.server.process
    until(lambda: backend.submitted > 0)
    backend.stop()
    assert second.poll() is not None
    print('PASS: restart produces audio; stop terminates owned process', flush=True)
    backend.say('Testing viewer shutdown.')
    third = backend.server.process
    backend.shutdown()
    assert third.poll() is not None
    print('PASS: backend shutdown terminates owned process', flush=True)
finally:
    backend.shutdown()
    widget.close()
print('ALL SMOKE CHECKS PASSED', flush=True)
