import array
from pathlib import Path
import wave
from calibre_extensions.ffmpeg import resample_raw_audio_16bit

root = Path(__file__).resolve().parent.parent
out = root / 'validation/ming-read-aloud'
with wave.open(str(root/'Sample.wav')) as w:
    raw = w.readframes(w.getnframes())
    rate, channels = w.getframerate(), w.getnchannels()
values = array.array('h', raw)
mono = array.array('h', (round(sum(values[i:i+channels])/channels) for i in range(0,len(values),channels))).tobytes()
for name, pcm, hz in [
    ('Sample-ffmpeg-44100.wav',resample_raw_audio_16bit(raw,rate,44100,channels,1),44100),
    ('Sample-unity-44100.wav',resample_raw_audio_16bit(mono,rate,44100,1,1),44100),
    ('Sample-unity-48000.wav',mono,rate),
]:
    with wave.open(str(out/name),'wb') as w:
        w.setparams((1,2,hz,0,'NONE','not compressed'))
        w.writeframes(pcm)
    x=array.array('h',pcm)
    print(name,'peak',max(abs(v) for v in x)/32768,'frames',len(x),flush=True)
