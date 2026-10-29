"""Model presets; preserve each profile while keeping shared server paths."""
import copy

from calibre_plugins.audio_cpp_read_aloud.core import model_family
from calibre_plugins.audio_cpp_read_aloud.model_catalog import CATALOG

PROFILE_KEYS = ('profile', 'model', 'voice', 'voices', 'language', 'sample_rate', 'channels',
                'supports_speed', 'options', 'server_settings', 'breeze_voice_mode',
                'breeze_instruction', 'reference_audio', 'reference_text')


def kokoro_server():
    return dict(host='127.0.0.1', backend='cpu', lazy_load=True, max_loaded_models=1,
                models=[dict(id='kokoro', family='kokoro_tts', path='', task='tts', mode='streaming',
                             default_voice_preset={'voice_id': 'af_heart'},
                             voice_presets={'heart': {'voice_id': 'af_heart'},
                                            'michael': {'voice_id': 'am_michael'}})])


def preset(name):
    common = dict(profile=name, language='en', sample_rate=24000, channels=1,
                  breeze_voice_mode='design', breeze_instruction='Speak clearly and naturally.',
                  reference_audio='', reference_text='')
    family = {'kokoro': 'kokoro_tts', 'breeze': 'breeze_tts'}.get(name, name)
    if family in CATALOG:
        spec = CATALOG[family]
        request_options = spec.get('options', {}).get('request', [])
        speed = next((o for o in request_options if o['name'] == 'speed'), {})
        languages = spec.get('languages', [])
        common.update(model=name, voice=spec.get('default_voice', ''),
                      voices=list(spec.get('voices', [])),
                      language='en' if 'en' in languages else next(iter(languages), 'en'),
                      breeze_instruction='', supports_speed=speed.get('type') in ('float', 'int'),
                      options={}, server_settings=dict(host='127.0.0.1', backend='cpu',
                          lazy_load=True, max_loaded_models=1,
                          models=[dict(id=name, family=family, path='', task='tts', mode='offline')]))
        if name == 'ming3_tts':
            common.update(sample_rate=44100, channels=1, supports_speed=False)
    else:
        raise ValueError('Unknown model preset: ' + name)
    return common


def profile_name(config):
    family = model_family(config)
    return {'kokoro_tts': 'kokoro', 'breeze_tts': 'breeze'}.get(family, family or config.get('profile', 'kokoro'))


def upgrade_ming_profile(config):
    """Upgrade known legacy defaults without replacing custom model settings."""
    family = model_family(config)
    if family == 'kokoro_tts' and config.get('voices') == ['heart', 'michael']:
        config['voices'] = list(CATALOG[family]['voices'])
        config['voice'] = {'heart': 'af_heart', 'michael': 'am_michael'}.get(config.get('voice'), config.get('voice', ''))
    if family == 'breeze_tts' and config.get('voices') == ['breeze']:
        config['voices'] = list(CATALOG[family].get('voices', []))
    if profile_name(config) == 'ming3_tts':
        config.update(sample_rate=44100, channels=1, supports_speed=False)
        if not config.get('voices'):
            config['voices'] = list(CATALOG['ming3_tts']['voices'])
    return config


def switch_profile(config, name):
    result = copy.deepcopy(config)
    old_name = profile_name(config)
    if name == old_name:
        return upgrade_ming_profile(result)
    saved = result.setdefault('model_profiles', {})
    saved[old_name] = {k: copy.deepcopy(config[k]) for k in PROFILE_KEYS if k in config}
    target = copy.deepcopy(saved.get(name, preset(name)))
    for key in PROFILE_KEYS:
        result.pop(key, None)
    result.update(target)
    # Conditioning follows the reader when changing model presets.
    for key in ('breeze_voice_mode', 'breeze_instruction', 'reference_audio', 'reference_text'):
        if key in config:
            result[key] = copy.deepcopy(config[key])
    result['profile'] = name
    return upgrade_ming_profile(result)
