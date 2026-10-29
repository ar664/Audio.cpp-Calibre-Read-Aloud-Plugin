"""Compare Ming conditioning using the user's reference, with local ASR checks."""
import array
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen
import wave

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/ming-read-aloud'
OUT.mkdir(exist_ok=True)
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'calibre-config')
from calibre.customize.zipplugin import loader
loader.load(str(ROOT / 'audio-cpp-read-aloud-0.6.1.zip'))
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, decode_wav, speech_request
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
from calibre_plugins.audio_cpp_read_aloud.settings import DEFAULTS

reference = ROOT / 'Sample.wav'
transcript = (ROOT / 'Sample.txt').read_text(encoding='utf-8-sig').strip()
text = 'The train arrived at the station just before sunrise.'
with wave.open(str(reference), 'rb') as w:
    samples = array.array('h', w.readframes(w.getnframes()))
    channels, rate = w.getnchannels(), w.getframerate()
mono = [sum(samples[i:i+channels]) / channels for i in range(0, len(samples), channels)]
converted = array.array('h')
for i in range(int(len(mono) * 44100 / rate)):
    pos = i * rate / 44100
    left = int(pos)
    a, b = mono[left], mono[min(left + 1, len(mono)-1)]
    converted.append(round(a + (b-a) * (pos-left)))
normalized = OUT / 'Sample-mono-44100.wav'
with wave.open(str(normalized), 'wb') as w:
    w.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
    w.writeframes(converted.tobytes())

def transcribe(audio, name):
    dest = OUT / (name + '-asr.txt')
    command = [str(ROOT/'bin/audiocpp_cli.exe'), '--task', 'asr', '--family', 'moonshine_asr',
               '--model', str(ROOT/'models/Moonshine-Streaming-GGUF/moonshine-streaming-tiny-q8_0.gguf'),
               '--backend', 'cpu', '--audio', str(audio), '--text-out', str(dest)]
    proc = subprocess.run(command, capture_output=True, timeout=120)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors='replace'))
    return dest.read_text(encoding='utf-8').strip()

results = []
for precision, model in [
    ('q8', ROOT/'models/Ming-3.0-TTS-0.5B-GGUF/ming-3.0-tts-0.5b-q8_0.gguf'),
    ('bf16', ROOT/'models/Ming-3.0-TTS-0.5B-BF16-GGUF/ming-3.0-tts-0.5b-bf16.gguf'),
]:
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(preset('ming3_tts'))
    cfg.update(executable=str(ROOT/'bin/audiocpp_server.exe'), working_directory=str(ROOT/'bin'),
               log_file=str(OUT / (precision + '-clone.log')))
    cfg['server_settings']['backend'] = 'cuda'
    cfg['server_settings']['models'][0]['path'] = str(model)
    server = OwnedServer(cfg)
    try:
        base = server.start()
        deadline = time.monotonic() + 30
        while True:
            try:
                with urlopen(base+'/health', timeout=2) as response:
                    if response.status == 200: break
            except OSError:
                if time.monotonic() > deadline: raise
                time.sleep(.2)
        cases = [('default', None, ''), ('full_transcript', reference, transcript),
                 ('full_transcript_cached', reference, transcript), ('speaker_only', reference, ''),
                 ('mono_transcript', normalized, transcript), ('mono_speaker_only', normalized, '')]
        for case, ref, words in cases:
            label = precision + '-' + case
            print('START', label, flush=True)
            current = copy.deepcopy(cfg)
            if ref:
                current.update(breeze_voice_mode='reference', reference_audio=str(ref), reference_text=words)
            row = dict(case=label, input=text)
            start = time.monotonic()
            try:
                body = speech_request(current, text)
                req = Request(base+'/v1/audio/speech', data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
                with urlopen(req, timeout=300) as response:
                    pcm, rate, channels = decode_wav(response.read())
                dest = OUT / (label + '.wav')
                with wave.open(str(dest),'wb') as w:
                    w.setparams((channels,2,rate,0,'NONE','not compressed'))
                    w.writeframes(pcm)
                values = array.array('h',pcm)
                row.update(output=str(dest),seconds=len(pcm)/(rate*channels*2),
                           rms=math.sqrt(sum(v*v for v in values)/max(len(values),1))/32768,
                           recognized=transcribe(dest,label))
            except Exception as error:
                row['error']=str(error)
            row['wall_seconds'] = round(time.monotonic()-start,2)
            results.append(row)
            (OUT/'clone-diagnostics.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)
    finally:
        server.close()
