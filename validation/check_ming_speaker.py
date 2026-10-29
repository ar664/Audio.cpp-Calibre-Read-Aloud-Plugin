"""Compare CAMPPlus speaker embeddings for the reference, clone and a preset control."""
import array
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import argparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/ming-read-aloud'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--clone', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
if args.output:
    OUT = args.output.resolve()
    OUT.mkdir(exist_ok=True, parents=True)
MODEL = ROOT / 'models/Ming-3.0-TTS-0.5B-GGUF/ming-3.0-tts-0.5b-q8_0.gguf'
sources = {
    'reference': ROOT / 'Sample.wav',
    'clone': args.clone.resolve() if args.clone else OUT / 'reader-0.6.2-offline-clone.wav',
    'preset_control': ROOT / 'validation/model-tests/ming3-offline-US_Emma.wav',
}

def embedding(path):
    data = path.read_bytes()
    header_size = struct.unpack('<Q',data[:8])[0]
    header = json.loads(data[8:8+header_size])
    record = next(value for key,value in header.items() if key != '__metadata__')
    assert record['dtype']=='F32', record
    start, end = record['data_offsets']
    result = array.array('f',data[8+header_size+start:8+header_size+end])
    if sys.byteorder != 'little': result.byteswap()
    assert len(result)==192, len(result)
    return result

vectors = {}
for name, source in sources.items():
    target = OUT / (name + '-speaker.safetensors')
    command = [str(ROOT/'bin/audiocpp_cli.exe'),'--task','tts','--family','ming3_tts',
               '--model',str(MODEL),'--backend','cuda','--voice-ref',str(source),
               '--text','Hello.','--language','en',
               '--request-option','export_speaker_embedding_file='+str(target),
               '--out',str(OUT/(name+'-embedding-check.wav'))]
    result = subprocess.run(command,capture_output=True,timeout=180)
    (OUT/(name+'-speaker.log')).write_bytes(result.stdout+b'\n'+result.stderr)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors='replace'))
    vectors[name]=embedding(target)
    print('Exported',name,flush=True)
def cosine(a,b):
    return sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
report = {name:cosine(vectors['reference'],vector) for name,vector in vectors.items() if name!='reference'}
(OUT/'speaker-similarity.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
