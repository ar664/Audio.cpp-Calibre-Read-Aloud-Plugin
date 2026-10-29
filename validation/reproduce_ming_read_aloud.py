"""Reproduce saved Ming Read Aloud settings with Qt networking and muted hardware audio."""
import copy
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess
import re
import time
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/ming-read-aloud'
OUT.mkdir(exist_ok=True)
saved = json.loads((Path(os.environ['APPDATA']) / 'calibre/plugins/audio_cpp_read_aloud.json').read_text(encoding='utf-8'))
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'calibre-config')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from calibre.customize.zipplugin import loader
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--archive', type=Path, default=ROOT / 'audio-cpp-read-aloud-0.6.3.zip')
parser.add_argument('--voice', default='', help='Viewer voice identifier, or clone')
parser.add_argument('--mode', choices=['offline','streaming'], default='offline')
parser.add_argument('--speaker-only', action='store_true')
parser.add_argument('--default-voice', action='store_true')
parser.add_argument('--short-reference', action='store_true')
args = parser.parse_args()
archive = args.archive
loader.load(str(archive))
from calibre_plugins.audio_cpp_read_aloud import backend
from qt.core import QApplication, QMediaDevices

app = QApplication([])
print('Audio device:', QMediaDevices.defaultAudioOutput().description(), flush=True)
cfg = copy.deepcopy(saved)
cfg.update(performance_overlay=False, reference_audio=str(ROOT / 'Sample.wav'),
           reference_text=(ROOT / 'Sample.txt').read_text(encoding='utf-8-sig').strip(),
           log_file=str(OUT / 'server.log'))
cfg['server_settings']['models'][0]['mode'] = args.mode
if args.short_reference:
    short = OUT / 'Sample-title.wav'
    with wave.open(str(ROOT/'Sample.wav')) as source, wave.open(str(short),'wb') as target:
        target.setparams(source.getparams())
        target.writeframes(source.readframes(round(source.getframerate()*4.2)))
    cfg.update(reference_audio=str(short), reference_text=cfg['reference_text'].split('Mr.')[0].strip())
if args.speaker_only:
    cfg['reference_text'] = ''
if args.default_voice:
    cfg.update(breeze_voice_mode='design', reference_audio='', reference_text='')
label = 'reader-' + archive.stem.rsplit('-',1)[-1] + '-' + args.mode
label += '-default' if args.default_voice else '-speaker' if args.speaker_only else '-clone'
if args.short_reference:
    label += '-short'
if args.voice:
    label += '-selected-' + args.voice
reading_text = 'The train arrived at the station just before sunrise. A quiet voice announced the next departure while the passengers gathered their bags and stepped onto the platform.'
result = {'archive': str(archive), 'requests': [], 'states': [], 'highlights': []}
captured = bytearray()
original_request = backend.speech_request
def request(*args, **kwargs):
    body = original_request(*args, **kwargs)
    result['requests'].append(body)
    return body

def spin(b, seconds=120):
    deadline = time.monotonic() + seconds
    while b.active and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    return dict(active=b.active, error=b.error_message(), total=getattr(b, 'total', 0),
                submitted=getattr(b, 'submitted', 0), state=str(b._state),
                queued=len(b.buffer), processed_us=b.sink.processedUSecs() if b.sink else 0)

viewer_settings = backend.EngineSpecificSettings.create_from_config(backend.AudioCpp.engine_name, 'tts')
if args.voice:
    viewer_settings = viewer_settings._replace(voice_name=backend.CLONED_VOICE if args.voice == 'clone' else args.voice)
with patch.object(backend, 'load_plugin_settings', side_effect=lambda: copy.deepcopy(cfg)), patch.object(backend, 'speech_request', side_effect=request), patch.object(backend.EngineSpecificSettings, 'create_from_config', return_value=viewer_settings):
    b = backend.AudioCpp(parent=app)
    b.state_changed.connect(lambda state: result['states'].append(str(state)))
    b.saying.connect(lambda *args: result['highlights'].append(args))
    original_sink = b._make_sink
    def muted_sink():
        original_sink()
        b.sink.setVolume(0)
        device = b.output
        class Capture:
            def write(self, data):
                written = device.write(data)
                if written > 0:
                    captured.extend(data[:written])
                return written
        b.output = Capture()
    b._make_sink = muted_sink
    try:
        print('Prewarming with Sample.wav and Sample.txt', flush=True)
        b.prewarm()
        result['prewarm'] = spin(b)
        print(json.dumps(result['prewarm']), flush=True)
        print('Reading two sentences through the actual backend', flush=True)
        b.say(reading_text)
        result['reading'] = spin(b)
        audio = OUT / (label + '.wav')
        with wave.open(str(audio), 'wb') as wav:
            wav.setparams((b.audio_channels,2,b.audio_rate,0,'NONE','not compressed'))
            wav.writeframes(captured)
        result['reading']['output'] = str(audio)
        print(json.dumps(result['reading']), flush=True)
    finally:
        b.shutdown()
        b.config_timer.stop()
        (OUT / (label + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
if captured:
    transcript = OUT / (label + '-asr.txt')
    subprocess.run([str(ROOT/'bin/audiocpp_cli.exe'),'--task','asr','--family','moonshine_asr',
                    '--model',str(ROOT/'models/Moonshine-Streaming-GGUF/moonshine-streaming-tiny-q8_0.gguf'),
                    '--backend','cpu','--audio',str(audio),'--text-out',str(transcript)],
                   capture_output=True,check=True,timeout=120)
    recognized = transcript.read_text(encoding='utf-8').strip()
    expected = re.findall(r'\w+',reading_text.lower())
    actual = re.findall(r'\w+',recognized.lower())
    costs = list(range(len(actual)+1))
    for i, word in enumerate(expected,1):
        following = [i]
        for j, candidate in enumerate(actual,1):
            following.append(min(following[-1]+1,costs[j]+1,costs[j-1]+(word!=candidate)))
        costs = following
    result['reading'].update(recognized=recognized, word_error_rate=costs[-1]/len(expected))
    print(json.dumps(result['reading']),flush=True)
    (OUT / (label + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
raise SystemExit(bool(result['reading']['error'] or result['reading']['active'] or result['reading'].get('word_error_rate',1)>.25))
