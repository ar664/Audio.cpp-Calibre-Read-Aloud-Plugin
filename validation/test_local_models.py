"""Exercise installed models through the plugin's real HTTP request/decoder.

Run with calibre-debug -e; outputs and configuration remain under validation/.
No audio is played and the user's saved settings are not modified.
"""
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
import wave

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/model-tests'
OUT.mkdir(exist_ok=True)
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'calibre-config')
from calibre.customize.zipplugin import loader
plugin = loader.load(str(ROOT / 'audio-cpp-read-aloud-0.6.2.zip'))
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, SpeechEvents, decode_wav, speech_request
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
from calibre_plugins.audio_cpp_read_aloud.settings import DEFAULTS

saved_path = Path(os.environ['APPDATA']) / 'calibre/plugins/audio_cpp_read_aloud.json'
saved = json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.is_file() else {}
if not saved.get('espeak_data'):
    # Use an existing installation; do not install dependencies or change user prefs.
    python_root = Path(os.environ['LOCALAPPDATA']) / 'Python'
    for phontab in python_root.glob('*/Lib/site-packages/espeakng_loader/espeak-ng-data/phontab'):
        library = phontab.parent.parent / 'espeak-ng.dll'
        if library.is_file():
            saved.update(espeak_library=str(library), espeak_data=str(phontab.parent))
            break
results = []
for family, filename in (('kokoro_tts', 'kokoro-82m-q8_0.gguf'), ('breeze_tts', 'breeze-tts-2-q4_0.gguf')):
    for mode in ('offline', 'streaming'):
        label = family + '-' + mode
        cfg = dict(DEFAULTS)
        cfg.update(preset(family))
        cfg.update(executable=str(ROOT / 'bin/audiocpp_server.exe'),
                   working_directory=str(ROOT / 'bin'), log_file=str(OUT / (label + '.log')))
        for key in ('espeak_library', 'espeak_data'):
            cfg[key] = saved.get(key, '')
        cfg['server_settings']['backend'] = 'cuda'
        cfg['server_settings']['models'][0].update(path=str(ROOT / 'models' / filename), mode=mode)
        server = OwnedServer(cfg)
        start = time.monotonic()
        row = dict(family=family, mode=mode, model=filename,
                   size_bytes=(ROOT / 'models' / filename).stat().st_size,
                   minimum_size_verified=False)
        print('START', label, flush=True)
        try:
            base = server.start()
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(base + '/health', timeout=2) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if server.process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Server failed to become ready; see log')
                    time.sleep(.2)
            body = speech_request(cfg, 'Hello. This is a short reading test.')
            request = Request(base + '/v1/audio/speech', data=json.dumps(body).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=180) as response:
                if mode == 'streaming':
                    parser = SpeechEvents()
                    chunks = []
                    while data := response.read(8192):
                        chunks.extend(parser.feed(data))
                    parser.finish()
                    pcm, rate, channels = b''.join(chunks), 24000, 1
                else:
                    pcm, rate, channels = decode_wav(response.read(16 * 1024 * 1024 + 1))
            assert pcm and any(pcm), 'Empty or silent generated audio'
            assert len(pcm) % (channels * 2) == 0, 'Incomplete PCM frames'
            output = OUT / (label + '.wav')
            with wave.open(str(output), 'wb') as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(pcm)
            row.update(status='passed', sample_rate=rate, channels=channels,
                       audio_seconds=len(pcm) / (rate * channels * 2), output=str(output))
        except Exception as error:
            row.update(status='failed', error=str(error))
        finally:
            server.close()
        row['wall_seconds'] = round(time.monotonic() - start, 2)
        results.append(row)
        (OUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
raise SystemExit(any(row['status'] != 'passed' for row in results))
