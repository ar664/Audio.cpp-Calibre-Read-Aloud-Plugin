"""Live reference-conditioning and Mio package-directory regression checks."""
import json, os, time, wave, subprocess, argparse
from pathlib import Path
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/miotts-0.9.2'
OUT.mkdir(exist_ok=True)
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'config')
from calibre.customize.zipplugin import loader
loader.load(str(ROOT / 'audio-cpp-read-aloud-0.9.2.zip'))
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, speech_request, decode_wav
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
short = OUT / 'reference.wav'
with wave.open(str(ROOT/'Sample.wav')) as src, wave.open(str(short), 'wb') as dst:
    dst.setparams(src.getparams())
    dst.writeframes(src.readframes(round(src.getframerate()*4.2)))
transcript = (ROOT/'Sample.txt').read_text(encoding='utf-8-sig').split('Mr.')[0].strip()
parser = argparse.ArgumentParser()
parser.add_argument('--family')
parser.add_argument('--explicit-paths', action='store_true')
args = parser.parse_args()
report = []
for family, directory in [('dots_tts','DotTTS-SOAR-GGUF'), ('miotts','MioTTS-1.7B-GGUF')]:
    if args.family and family != args.family: continue
    cfg = preset(family)
    cfg.update(executable=str(ROOT/'bin/audiocpp_server.exe'), working_directory=str(ROOT/'bin'),
               log_file=str(OUT/(family+'.log')), breeze_voice_mode='reference',
               reference_audio=str(short), reference_text=transcript, language='en')
    cfg['server_settings']['backend']='cuda'
    cfg['server_settings']['models'][0]['path']=str(ROOT/'models'/directory)
    if args.explicit_paths:
        entry = cfg['server_settings']['models'][0]
        entry['path'] = str(next((ROOT/'models'/directory).glob('*.gguf')))
        if family == 'miotts':
            entry['session_options'] = {'miotts.codec_model_path': str(ROOT/'models'/directory/'MioCodec-25Hz-44.1kHz-v2')}
    cfg['options']['seed']=123
    server=OwnedServer(cfg)
    try:
        base=server.start()
        for attempt in range(150):
            try:
                urlopen(base+'/health',timeout=2).close(); break
            except OSError:
                time.sleep(.2)
        cases = [('short',short,transcript), ('full',ROOT/'Sample.wav',(ROOT/'Sample.txt').read_text(encoding='utf-8-sig'))]
        if family == 'miotts':
            cases = [('known',ROOT/'validation/model-tests/breeze_tts-offline.wav','Hello. This is a short reading test.'), ('sample',ROOT/'Sample.wav',(ROOT/'Sample.txt').read_text(encoding='utf-8-sig'))]
        for label, reference, words in cases:
            if args.explicit_paths: label += '-explicit'
            if family=='miotts' and label=='full': continue
            cfg.update(reference_audio=str(reference), reference_text=words)
            text='The train arrived at the station just before sunrise.'
            body=speech_request(cfg,text)
            print('START',family,label,flush=True)
            row=dict(family=family,case=label,request=body)
            try:
                request=Request(base+'/v1/audio/speech',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=300) as response: pcm,rate,channels=decode_wav(response.read())
                audio=OUT/(family+'-'+label+'.wav')
                with wave.open(str(audio),'wb') as dst:
                    dst.setparams((channels,2,rate,0,'NONE','not compressed'));dst.writeframes(pcm)
                asr=audio.with_suffix('.txt')
                subprocess.run([str(ROOT/'bin/audiocpp_cli.exe'),'--task','asr','--family','moonshine_asr','--model',str(ROOT/'models/Moonshine-Streaming-GGUF/moonshine-streaming-tiny-q8_0.gguf'),'--backend','cpu','--audio',str(audio),'--text-out',str(asr)],capture_output=True,check=True,timeout=120)
                row.update(seconds=len(pcm)/2/channels/rate,recognized=asr.read_text(encoding='utf-8'),output=str(audio))
            except Exception as e:
                row['error']=str(e)
                if hasattr(e,'read'): row['detail']=e.read().decode(errors='replace')
            report.append(row)
            (OUT/('results-'+(args.family or 'all')+('-explicit' if args.explicit_paths else '')+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)
    finally: server.close()
