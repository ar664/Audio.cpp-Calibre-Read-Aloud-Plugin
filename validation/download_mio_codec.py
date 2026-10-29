"""Fetch MioTTS's required, MIT-licensed MioCodec companion checkpoint."""
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parent.parent
folder = root / 'models/MioTTS-1.7B-GGUF/MioCodec-25Hz-44.1kHz-v2'
folder.mkdir(parents=True, exist_ok=True)
files = {
    'config.yaml': 'Aratako/MioCodec-25Hz-44.1kHz-v2',
    'model.safetensors': 'Aratako/MioCodec-25Hz-44.1kHz-v2',
    'wavlm-base-plus-mlx/config.json': 'mlx-community/wavlm-base-plus-mlx',
    'wavlm-base-plus-mlx/weights.safetensors': 'mlx-community/wavlm-base-plus-mlx',
}
for relative, repo in files.items():
    target = folder / relative
    if target.is_file() and target.stat().st_size > 0:
        print('Already installed:', target, target.stat().st_size, flush=True)
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.part')
    request = f'https://huggingface.co/{repo}/resolve/main/{target.name}'
    with urlopen(request, timeout=300) as response, partial.open('wb') as output:
        expected = int(response.headers.get('Content-Length', 0))
        copied = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            copied += len(chunk)
            if copied % (64 * 1024 * 1024) < 1024 * 1024:
                print(f'{relative}: {copied}/{expected}', flush=True)
    if expected and copied != expected:
        raise RuntimeError(f'{relative} size mismatch: {copied} != {expected}')
    partial.replace(target)
    print('Installed:', target, copied, flush=True)
