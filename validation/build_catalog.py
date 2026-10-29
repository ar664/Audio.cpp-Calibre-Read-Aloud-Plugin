"""Generate the bundled TTS catalog from an audio.cpp model_specs directory."""
import argparse
import json
from pathlib import Path
import pprint
import runpy
import sys

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', nargs='?', type=Path, default=root / 'bin/model_specs')
parser.add_argument('--family', action='append', help='Refresh only this family; repeatable')
args = parser.parse_args()
source = args.source
catalog = {}
for path in sorted(source.glob('*.json')):
    spec = json.loads(path.read_text(encoding='utf-8'))
    if 'tts' not in spec.get('tasks', []) or not any(s.get('format') == 'gguf' for s in spec.get('sources', [])):
        continue
    options = spec.get('options', {})
    voice = next((o for o in options.get('request', []) if o['name'] == 'voice_id'), {})
    ui = spec.get('ui', {})
    catalog[spec['family']] = dict(
        name=spec.get('display_name', spec['family']), status=spec.get('status', 'unknown'),
        modes=spec.get('modes', ['offline']), languages=spec.get('languages', []),
        voices=ui.get('builtin_voices', voice.get('values', [])),
        default_voice=ui.get('default_voice', voice.get('default', '')),
        options=options,
    )
# Families added since the local binary's catalog. Use offline WAV until the
# installed server's newer spec is available. Their controls remain available
# through Advanced JSON; do not invent model defaults from names.
for family, name, status, languages in (
    ('ming3_tts', 'Ming 3.0 TTS 0.5B', 'supported', ['zh', 'en', 'ja', 'ko', 'de', 'fr', 'es']),
    ('ming3_audio', 'Ming 3.0 Audio Tiny', 'supported', ['zh', 'en']),
    ('gradium_phonon', 'Gradium Phonon 31m', 'supported', ['en']),
    ('xtts_v2', 'Coqui XTTS v2', 'community', ['en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh-cn', 'hu', 'ko', 'ja', 'hi']),
):
    catalog.setdefault(family, dict(name=name, status=status, modes=['offline'], languages=languages,
                                   voices=[], default_voice='', options={}))
if not catalog['ming3_tts']['options']:
    catalog['ming3_tts']['options'] = {'request': [
        {'name': 'instruct', 'type': 'string', 'description': 'Voice description or raw conditioning text.'},
        {'name': 'language', 'type': 'string', 'description': 'Language name or code.'},
        {'name': 'template_name', 'type': 'enum', 'values': ['tts', 'multilingual', 'basic', 'emotion', 'dialect', 'ip', 'voice_design', 'freeform']},
    ]}
if args.family:
    previous = runpy.run_path(str(root / 'model_catalog.py'))['CATALOG']
    for family in args.family:
        if family not in catalog:
            parser.error('Unknown family: ' + family)
        previous[family] = catalog[family]
    catalog = previous
(root / 'model_catalog.py').write_text(
    '"""Generated audio.cpp GGUF TTS catalog; see validation/build_catalog.py.\n'
    'Source: audio.cpp model_specs, with upstream family additions checked 2026-10-27.\n'
    'Model status describes upstream, not local inference validation.\n"""\n\nCATALOG = '
    + pprint.pformat(catalog, width=110, sort_dicts=True) + '\n', encoding='utf-8')
print('Generated', len(catalog), 'GGUF TTS families')
