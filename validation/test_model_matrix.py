"""Live offline inference through the packaged plugin, one server at a time."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'validation/model-tests'
OUT.mkdir(exist_ok=True)
os.environ['CALIBRE_CONFIG_DIRECTORY'] = str(OUT / 'calibre-config')
sys.path.insert(0, str(ROOT / 'bin/tools'))
import model_manager_v2 as manager
from calibre.customize.zipplugin import loader
loader.load(str(ROOT / 'audio-cpp-read-aloud-0.6.2.zip'))
from calibre_plugins.audio_cpp_read_aloud.core import OwnedServer, decode_wav, speech_request
from calibre_plugins.audio_cpp_read_aloud.profiles import preset
from calibre_plugins.audio_cpp_read_aloud.settings import DEFAULTS

specs = {s['family']: s for s in manager.load_specs(ROOT / 'bin/model_specs')}
packages = {p.id: p for p in manager.flatten_packages(list(specs.values()))}
REFERENCE_TEXT = 'Hello. This is a short reading test.'
reference = OUT / 'breeze_tts-offline.wav'
TEXTS = {'ja': 'こんにちは。これは短い読み上げテストです。', 'zh': '你好。这是一个简短的朗读测试。',
         'da': 'Hej. Dette er en kort oplæsningstest.', 'ar': 'مرحبا. هذا اختبار قصير للقراءة.',
         'fr': 'Bonjour. Ceci est un court test de lecture.', 'es': 'Hola. Esta es una breve prueba de lectura.',
         'de': 'Hallo. Dies ist ein kurzer Lesetest.', 'vi': 'Xin chào. Đây là bài kiểm tra đọc ngắn.'}


def configuration(row):
    family = row['family']
    override_path = OUT / 'overrides.json'
    overrides = json.loads(override_path.read_text(encoding='utf-8')) if override_path.exists() else {}
    override = overrides.get(family, {})
    package = packages[override.get('package', row['package'])]
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(preset(family))
    root = ROOT / 'models' / package.target_directory
    ggufs = [root / manager.stripped_path(p, package.strip_prefix) for p in package.files if p.endswith('.gguf')]
    model = max(ggufs, key=lambda p: p.stat().st_size)
    cfg.update(executable=str(ROOT / 'bin/audiocpp_server.exe'), working_directory=str(ROOT / 'bin'),
               log_file=str(OUT / (family + '-matrix.log')))
    cfg['server_settings']['backend'] = 'cuda'
    entry = cfg['server_settings']['models'][0]
    entry.update(path=str(model), mode='offline')
    params = {p['name']: p for p in specs[family].get('options', {}).get('request', [])}
    cfg['breeze_instruction'] = 'A calm narrator speaking clearly and naturally.' if any(k in params for k in ('instruct', 'instruction', 'voice_description', 'description')) else ''
    if 'max_tokens' in params:
        cfg['options']['max_tokens'] = max(params['max_tokens'].get('min', 1), min(params['max_tokens'].get('default', 256) or 256, 256))
    if 'seed' in params:
        cfg['options']['seed'] = 123
    if family in ('vibevoice',):
        cfg['options'].pop('max_tokens', None)
    if family == 'lfm2_audio':
        cfg['language'] = 'ja'
        cfg['voice'] = ''
        cfg['options']['language'] = 'ja'
    if family == 'minimax_h3':
        cfg['options'].pop('max_tokens', None)
        cfg['options'].update(num_frames=16, return_video=False)
    if family in ('inflect_v2', 'piper_tts', 'sanotts', 'kitten_tts', 'kitten_tts2', 'zipvoice'):
        # eSpeak is read by session initialization, rather than from env vars.
        cfg['espeak_library'] = str(Path(os.environ['LOCALAPPDATA']) / 'Python/pythoncore-3.14-64/Lib/site-packages/espeakng_loader/espeak-ng.dll')
        cfg['espeak_data'] = str(Path(os.environ['LOCALAPPDATA']) / 'Python/pythoncore-3.14-64/Lib/site-packages/espeakng_loader/espeak-ng-data')
        entry['session_options'] = {f'{family}.espeak_library_path': cfg['espeak_library'],
                                    f'{family}.espeak_data_path': cfg['espeak_data']}
    if family == 'miotts':
        cfg['language'] = 'en'
        codec = ROOT / 'models/MioTTS-1.7B-GGUF/MioCodec-25Hz-44.1kHz-v2'
        entry['session_options'] = {'miotts.codec_model_path': str(codec)}
    if family == 'irodori_tts':
        cfg['breeze_instruction'] = ''
        cfg['language'] = 'ja'
        cfg['breeze_voice_mode'] = 'design'
        cfg['reference_audio'] = ''
        cfg['reference_text'] = ''
    if family == 'omnivoice':
        cfg['language'] = 'en'
        cfg['breeze_instruction'] = ''
    if family == 'outetts':
        cfg['options']['max_tokens'] = 4096
    if family == 'vibevoice':
        cfg['breeze_voice_mode'] = 'design'
    if family == 'vevo2':
        cfg['language'] = 'en'
        cfg['options']['target_voice'] = str(reference)
        cfg['options']['route'] = 'zero_shot_tts'
    if family == 'dramabox':
        cfg['options'].pop('max_tokens', None)
        cfg['options'].update(duration_sec=3, num_inference_steps=8)
        cfg['breeze_voice_mode'] = 'design'
        cfg['reference_audio'] = ''
        cfg['reference_text'] = ''
    if (family not in ('auk', 'dramabox', 'vibevoice', 'irodori_tts') and not cfg.get('voice')
            and ('clone' in specs[family].get('tasks', []) or 'reference_text' in params)):
        cfg.update(breeze_voice_mode='reference', reference_audio=str(reference), reference_text=REFERENCE_TEXT)
    if family == 'auk':
        entry['path'] = str(root)
        entry['session_options'] = {'auk.variant': 'flash' if 'flash' in package.id else 'base',
            'auk.model_gguf': model.name, 'auk.qwen_gguf': 'qwen2.5-omni-3b-q8_0.gguf',
            'auk.vae_gguf': 'auk-vae-f32.gguf', 'auk.mem_saver': True}
        cfg['options']['duration_sec'] = 4
    if family == 'f5_tts':
        companion = packages['vocos_mel_24khz']
        vocos = ROOT / 'models' / companion.target_directory / manager.stripped_path(companion.files[0], companion.strip_prefix)
        entry['session_options'] = {'f5_tts.vocoder_gguf': str(vocos)}
        cfg['language'] = 'ar'
    # Variant-specific settings can be recorded once and replayed without editing code.
    cfg.update(override.get('config', {}))
    cfg['options'].update(override.get('options', {}))
    entry.update(override.get('model', {}))
    if 'backend' in override:
        cfg['server_settings']['backend'] = override['backend']
    text = override.get('text', TEXTS.get(cfg['language'], REFERENCE_TEXT))
    return cfg, text


def run(row, timeout):
    family = row['family']
    result = dict(family=family, package=row['package'], package_bytes=row['size_bytes'],
                  mode='offline', status='failed')
    start = time.monotonic()
    server = None
    try:
        cfg, text = configuration(row)
        result['backend'] = cfg['server_settings']['backend']
        override_path = OUT / 'overrides.json'
        overrides = json.loads(override_path.read_text(encoding='utf-8')) if override_path.exists() else {}
        selected_package = overrides.get(family, {}).get('package', row['package'])
        if selected_package != row['package']:
            result['package'] = selected_package
            for item in json.loads((ROOT / 'validation/model-downloads.json').read_text(encoding='utf-8'))['families']:
                if item['family'] == family:
                    result['package_bytes'] = next((size['size_bytes'] for size in item.get('sizes', [])
                                                    if size['id'] == selected_package), row['size_bytes'])
                    break
        if family == 'minimax_h3':
            model = ROOT / 'models' / packages[selected_package].target_directory / 'dit.gguf'
            output = OUT / 'minimax_h3-matrix.wav'
            log = OUT / 'minimax_h3-matrix.log'
            command = [str(ROOT / 'bin/audiocpp_cli.exe'), '--task', 'gen', '--family', family,
                       '--model', str(model), '--backend', 'cuda', '--threads', '8', '--text',
                       'A short, gentle instrumental melody.', '--num-inference-steps', '2',
                       '--request-option', 'num_frames=16', '--request-option', 'height=256',
                       '--request-option', 'width=256', '--out', str(output), '--metrics', '--log-file', str(log)]
            completed = subprocess.run(command, cwd=ROOT / 'bin', capture_output=True, text=True, timeout=timeout)
            if completed.returncode:
                raise RuntimeError((completed.stdout + '\n' + completed.stderr)[-8000:])
            with wave.open(str(output), 'rb') as wav:
                rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
            if not frames:
                raise ValueError('Empty generated audio')
            result.update(status='passed', task='gen', sample_rate=rate, channels=channels,
                          audio_seconds=round(frames / rate, 3), output=str(output))
            result['wall_seconds'] = round(time.monotonic() - start, 2)
            return result
        (OUT / (family + '-test-config.json')).write_text(json.dumps(cfg, indent=2), encoding='utf-8')
        server = OwnedServer(cfg)
        base = server.start()
        deadline = time.monotonic() + 30
        while True:
            try:
                with urlopen(base + '/health', timeout=2) as response:
                    assert response.status == 200
                break
            except OSError:
                if server.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Server failed to become ready; see log')
                time.sleep(.2)
        body = speech_request(cfg, text)
        if family == 'dramabox':
            body.pop('voice_ref', None)
            body.pop('reference_text', None)
            body.setdefault('options', {})['target_voice'] = str(reference)
        (OUT / (family + '-test-request.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
        request = Request(base + '/v1/audio/speech', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=timeout) as response:
            data = response.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                raise ValueError('Generated clip exceeds plugin limit')
            pcm, rate, channels = decode_wav(data)
        if not pcm or not any(pcm):
            raise ValueError('Empty or silent generated audio')
        output = OUT / (family + '-matrix.wav')
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        result.update(status='passed', sample_rate=rate, channels=channels,
                      audio_seconds=round(len(pcm) / (rate * channels * 2), 3), output=str(output))
    except HTTPError as error:
        result['error'] = str(error) + ': ' + error.read(8000).decode('utf-8', errors='replace')
    except Exception as error:
        result['error'] = str(error)
    finally:
        if server is not None:
            server.close()
    result['wall_seconds'] = round(time.monotonic() - start, 2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--family', action='append')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    report = OUT / 'matrix-results.json'
    results = json.loads(report.read_text(encoding='utf-8')) if report.exists() else []
    seen = {r['family'] for r in results} - set(args.family or [])
    while True:
        try:
            downloads = json.loads((ROOT / 'validation/model-downloads.json').read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        for row in downloads['families']:
            family = row['family']
            if row['status'] != 'installed' or family in seen or (args.family and family not in args.family):
                continue
            print('START', family, flush=True)
            result = run(row, args.timeout)
            results = [r for r in results if r['family'] != family] + [result]
            report.write_text(json.dumps(results, indent=2), encoding='utf-8')
            seen.add(family)
            print(json.dumps(result), flush=True)
        if not args.watch or downloads.get('complete'):
            break
        time.sleep(2)
    return int(any(r['status'] != 'passed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
