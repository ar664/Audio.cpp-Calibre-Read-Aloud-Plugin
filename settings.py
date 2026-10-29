"""Persistent settings and migration from the working source-patch prototype."""
import copy
import json
import os
from pathlib import Path

from calibre.constants import config_dir
from calibre.utils.config import JSONConfig

DEFAULTS = dict(
    prewarm_on_open=False, keep_loaded_while_open=False,
    performance_overlay=False,
    pronunciation_enabled=True, pronunciation_case_sensitive=False, pronunciations=[],
    mode='managed', executable='', model='kokoro', voice='heart',
    voices=['heart', 'michael'], language='en', sample_rate=24000, channels=1,
    supports_speed=True, options={'text_chunk_size': 160},
    idle_shutdown_seconds=60, startup_timeout_seconds=120, request_timeout_seconds=300,
    base_url='http://127.0.0.1:8080', espeak_library='', espeak_data='',
    working_directory='', server_settings={},
    breeze_voice_mode='design', breeze_instruction='Speak clearly and naturally.',
    reference_audio='', reference_text='', model_profiles={},
    reference_voices={},
)


def load():
    from calibre_plugins.audio_cpp_read_aloud.profiles import upgrade_ming_profile
    result = copy.deepcopy(DEFAULTS)
    from calibre_plugins.audio_cpp_read_aloud.profiles import preset
    result.update(preset('kokoro'))
    result.update(dict(JSONConfig('plugins/audio_cpp_read_aloud')))
    upgrade_ming_profile(result)
    for profile in result.get('model_profiles', {}).values():
        upgrade_ming_profile(profile)
    result['log_file'] = str(Path(config_dir) / 'plugins' / 'audio_cpp_read_aloud-server.log')
    return result


def save(values):
    prefs = JSONConfig('plugins/audio_cpp_read_aloud')
    with prefs:
        prefs.clear()
        prefs.update(copy.deepcopy(values))


def import_prototype(filename):
    path = Path(filename).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    result = copy.deepcopy(DEFAULTS)
    result.update(data)
    def absolute(value):
        p = Path(value).expanduser()
        return str(p if p.is_absolute() else (path.parent / p).resolve())
    if data.get('executable'):
        result['executable'] = absolute(data['executable'])
    if result['mode'] == 'managed':
        server_path = Path(absolute(data['server_config']))
        result['server_settings'] = json.loads(server_path.read_text(encoding='utf-8-sig'))
        result['working_directory'] = str(server_path.parent)
        # Decouple normal model paths from the old prototype folder.
        for model in result['server_settings'].get('models', []):
            if model.get('path'):
                p = Path(model['path'])
                if not p.is_absolute():
                    model['path'] = str((server_path.parent / p).resolve())
    result.pop('server_config', None)
    result.pop('log_file', None)
    # The known-working environment may have been configured in PowerShell.
    result['espeak_library'] = data.get('espeak_library') or os.getenv('AUDIOCPP_ESPEAK_LIBRARY', '')
    result['espeak_data'] = data.get('espeak_data') or os.getenv('AUDIOCPP_ESPEAK_DATA', '')
    return result
