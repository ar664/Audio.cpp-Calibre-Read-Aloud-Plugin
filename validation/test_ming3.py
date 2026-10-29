"""Live Ming3-TTS checks through the installable plugin and bundled server.

Run with calibre-debug -e. Does not modify user preferences or play audio.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/model-tests'
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'calibre-config')
from calibre.customize.zipplugin import loader
loader.load(str(ROOT / 'audio-cpp-read-aloud-0.6.2.zip'))
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, SpeechEvents, decode_wav, speech_request
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
from calibre_plugins.audio_cpp_read_aloud.settings import DEFAULTS

model = ROOT / 'models/Ming-3.0-TTS-0.5B-GGUF/ming-3.0-tts-0.5b-q8_0.gguf'
reference = OUT / 'breeze_tts-offline.wav'
text = 'Hello. This is a short reading test.'
report = dict(plugin_version='0.6.2',
              audio_cpp_version=subprocess.check_output([str(ROOT / 'bin/audiocpp_cli.exe'), '--version'], text=True).strip(),
              family='ming3_tts', package='ming_3_0_tts_0_5b_q8_0',
              model=str(model), size_bytes=model.stat().st_size, backend='cuda', language='en', cases=[])

cases = [('default', {}, '')]
cases += [(voice, {}, voice) for voice in preset('ming3_tts')['voices']]
cases += [
    ('voice_design', {'breeze_instruction': 'A calm adult man with a clear, warm voice.'}, 'US_Emma'),
    ('reference', {'breeze_voice_mode': 'reference', 'reference_audio': str(reference)}, 'US_Emma'),
    ('reference_transcript', {'breeze_voice_mode': 'reference', 'reference_audio': str(reference),
                              'reference_text': text}, 'US_Emma'),
]
for mode in ('offline', 'streaming'):
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(preset('ming3_tts'))
    cfg.update(executable=str(ROOT / 'bin/audiocpp_server.exe'), working_directory=str(ROOT / 'bin'),
               log_file=str(OUT / f'ming3-{mode}.log'))
    cfg['server_settings']['backend'] = 'cuda'
    cfg['server_settings']['models'][0].update(path=str(model), mode=mode)
    cfg['options']['seed'] = 1895
    server = OwnedServer(cfg)
    try:
        base = server.start()
        deadline = time.monotonic() + 30
        while True:
            try:
                with urlopen(base + '/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                if server.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Ming3 server failed to start; see log')
                time.sleep(.2)
        for case, changes, voice in cases:
            label = f'ming3-{mode}-{case}'
            row = dict(case=case, mode=mode, status='failed')
            start = time.monotonic()
            print('START', label, flush=True)
            try:
                current = copy.deepcopy(cfg)
                current.update(changes)
                body = speech_request(current, text, voice)
                (OUT / (label + '-request.json')).write_text(json.dumps(body, indent=2), encoding='utf-8')
                request = Request(base + '/v1/audio/speech', data=json.dumps(body).encode(),
                                  headers={'Content-Type': 'application/json'})
                with urlopen(request, timeout=300) as response:
                    if mode == 'streaming':
                        parser = SpeechEvents()
                        chunks = []
                        size = 0
                        while data := response.read1(8192):
                            for chunk in parser.feed(data):
                                size += len(chunk)
                                if size > 16 * 1024 * 1024:
                                    raise ValueError('Generated audio exceeds plugin limit')
                                chunks.append(chunk)
                        parser.finish()
                        pcm, rate, channels = b''.join(chunks), current['sample_rate'], current['channels']
                        row['pcm_chunks'] = len(chunks)
                    else:
                        data = response.read(16 * 1024 * 1024 + 1)
                        if len(data) > 16 * 1024 * 1024:
                            raise ValueError('Generated audio exceeds plugin limit')
                        pcm, rate, channels = decode_wav(data)
                assert (rate, channels) == (44100, 1), (rate, channels)
                assert pcm and any(pcm), 'Empty or silent output'
                assert len(pcm) % (2 * channels) == 0, 'Incomplete PCM frames'
                output = OUT / (label + '.wav')
                with wave.open(str(output), 'wb') as wav:
                    wav.setnchannels(channels)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(pcm)
                row.update(status='passed', sample_rate=rate, channels=channels,
                           audio_seconds=round(len(pcm) / (rate * channels * 2), 3), output=str(output))
            except HTTPError as error:
                row['error'] = str(error) + ': ' + error.read(8000).decode(errors='replace')
            except Exception as error:
                row['error'] = str(error)
            row['wall_seconds'] = round(time.monotonic() - start, 2)
            report['cases'].append(row)
            (OUT / 'ming3-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(row), flush=True)
    finally:
        server.close()
offline = next(row for row in report['cases'] if row['mode'] == 'offline' and row['case'] == 'default')
matrix_path = OUT / 'matrix-results.json'
matrix = json.loads(matrix_path.read_text(encoding='utf-8')) if matrix_path.exists() else []
matrix = [row for row in matrix if row['family'] != 'ming3_tts']
matrix.append(dict(offline, family='ming3_tts', package=report['package'],
                   package_bytes=report['size_bytes'], backend=report['backend'],
                   plugin_version=report['plugin_version'], audio_cpp_version=report['audio_cpp_version']))
matrix_path.write_text(json.dumps(matrix, indent=2), encoding='utf-8')
raise SystemExit(any(row['status'] != 'passed' for row in report['cases']))
