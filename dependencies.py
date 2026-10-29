"""Read-only checks using the selected binary's package specifications."""
import copy
import json
from pathlib import Path, PurePosixPath

from calibre_plugins.audio_cpp_read_aloud.core import resolve_mio_packages


def check_dependencies(config):
    if config.get('mode') == 'external':
        return ['External server: its files and installed families cannot be verified locally.']
    messages = []
    exe = Path(config.get('executable', '')).expanduser()
    if not exe.is_file():
        messages.append('MISSING: audio.cpp executable.')
    working = Path(config.get('working_directory') or exe.parent)
    server = copy.deepcopy(config.get('server_settings', {}))
    model = next((m for m in server.get('models', []) if m.get('id') == config.get('model')), None)
    if not model:
        return messages + ['MISSING: matching model entry in server configuration.']
    path = Path(model.get('path', '')).expanduser()
    if not path.is_absolute():
        path = working / path
    if not model.get('path') or not path.exists():
        return messages + ['MISSING: model GGUF or package directory: ' + str(path)]
    folder = path if path.is_dir() else path.parent
    spec_path = exe.parent / 'model_specs' / (model.get('family', '') + '.json')
    if spec_path.is_file():
        spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
        for group, settings_key in [('session', 'session_options'), ('load', 'load_options')]:
            configured = model.get(settings_key, {})
            for option in spec.get('options', {}).get(group, []):
                if option.get('type') not in ('path', 'audio_path'):
                    continue
                name = option['name']
                value = configured.get(model['family'] + '.' + name, configured.get(name))
                if value:
                    companion = Path(value).expanduser()
                    if not companion.is_absolute():
                        companion = working / companion
                    if not companion.exists() and name != 'codec_model_path':
                        messages.append('MISSING: ' + name + ': ' + str(companion))
                elif option.get('required'):
                    messages.append('MISSING: required ' + name)
        packages = spec.get('packages', [])
        checked = False
        for manifest in folder.glob('.audiocpp-package-*.json'):
            installed = json.loads(manifest.read_text(encoding='utf-8-sig'))
            package = next((p for p in packages if p['id'] == installed.get('package_id')), None)
            if not package:
                continue
            prefix = package.get('strip_prefix', '').strip('/')
            files = []
            for name in package.get('files', []):
                relative = name[len(prefix)+1:] if prefix and name.startswith(prefix+'/') else name
                item = folder.joinpath(*PurePosixPath(relative).parts).resolve()
                if not item.is_relative_to(folder.resolve()):
                    raise ValueError('Invalid package file path: ' + name)
                files.append((name, item))
            if path.is_file() and path.resolve() not in [p for _, p in files]:
                continue
            checked = True
            for name, item in files:
                size = installed.get('files', {}).get(name, {}).get('size')
                if not item.is_file() or item.stat().st_size == 0:
                    messages.append('MISSING: ' + str(item))
                elif size and item.stat().st_size != size:
                    messages.append('SIZE MISMATCH: ' + str(item))
            messages.append('Checked package file list: ' + package['id'])
        if not checked:
            messages.append('No matching installation manifest; package completeness could not be verified.')
    else:
        messages.append('No adjacent model_specs entry; binary family support and package completeness are unverified.')
    if model.get('family') == 'miotts':
        try:
            resolve_mio_packages(server, working)
            messages.append('MioCodec GGUF: ' + model['session_options']['miotts.codec_model_path'])
        except ValueError as error:
            messages.append('MISSING/INVALID: ' + str(error))
    for label, key in [('eSpeak library', 'espeak_library'), ('eSpeak data', 'espeak_data')]:
        if config.get(key) and not Path(config[key]).exists():
            messages.append('MISSING: ' + label + ': ' + config[key])
    if config.get('breeze_voice_mode') == 'reference':
        if not Path(config.get('reference_audio') or '').is_file():
            messages.append('MISSING: reference WAV.')
    messages.append('File checks only: this does not prove inference compatibility or speech quality.')
    return messages
