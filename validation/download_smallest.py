"""Inventory or download the smallest published GGUF package per TTS family.

calibre-debug -e validation/download_smallest.py -- --download
Without --download, only writes a local inventory. Compares the sum of remote
file sizes (including package sidecars), never guesses from quantization names.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bin/tools'))
sys.path.insert(0, str(ROOT))
import model_manager_v2 as manager
from model_catalog import CATALOG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--family', action='append', help='Restrict to a family; repeatable')
    args = parser.parse_args()
    cli = ROOT / 'bin/audiocpp_cli.exe'
    raw = subprocess.check_output([str(cli), '--list-loaders', '--json'], text=True)
    loaders = json.loads(raw)['loaders']
    specs = manager.load_specs(ROOT / 'bin/model_specs')
    records = manager.flatten_packages(specs)
    by_id = {p.id: p for p in records}
    packages = defaultdict(list)
    for record in records:
        if record.format == 'gguf' and not record.id.startswith(('auk_qwen_', 'auk_vae_', 'vocos_')) and not record.id.startswith('dots_tts_edit_'):
            packages[record.family].append(record)
    families = sorted(CATALOG)
    requested = set(args.family or CATALOG)
    unknown = requested - set(CATALOG)
    if unknown:
        parser.error('Unknown speech families: ' + ', '.join(sorted(unknown)))
    report_path = ROOT / 'validation/model-downloads.json'
    old = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    old_rows = {r['family']: r for r in old.get('families', [])}
    report = {'models_root': str(ROOT / 'models'), 'families': []}
    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Cache shared tokenizer/codec sizes across precision variants.
    original_check = manager.check_remote_file
    cache = {}
    def cached_check(package, remote):
        key = (package.download.get('repo'), manager.package_revision(package), remote)
        if key not in cache:
            cache[key] = original_check(package, remote)
        return cache[key]
    manager.check_remote_file = cached_check
    for family in families:
        row = {'family': family, 'candidates': [p.id for p in packages[family]]}
        report['families'].append(row)
        if old_rows.get(family, {}).get('status') == 'installed':
            row.update(old_rows[family])
            continue
        if family not in requested and family in old_rows:
            row.update(old_rows[family])
            continue
        if 'tts' not in loaders.get(family, {}).get('tasks', {}):
            row['status'] = 'not_in_installed_binary'
        elif not packages[family]:
            row['status'] = 'no_published_gguf_package_in_local_spec'
        else:
            row['status'] = 'pending_remote_size_check'
        save()
    if not args.download:
        print(json.dumps({status: sum(r['status'] == status for r in report['families'])
                          for status in sorted({r['status'] for r in report['families']})}))
        print('Inventory:', report_path)
        return 0
    for row in report['families']:
        if row['status'] != 'pending_remote_size_check':
            continue
        family = row['family']
        print('Checking complete package sizes:', family, flush=True)
        sizes = []
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                sizes = list(pool.map(manager.package_size_record, packages[family]))
            row['sizes'] = sizes
            available = [s for s in sizes if s['state'] == 'ok' and s['size_bytes'] is not None]
            if not available:
                row['status'] = 'size_comparison_incomplete'
                save()
                continue
            row['minimum_scope'] = 'all candidates' if len(available) == len(sizes) else 'currently accessible candidates'
            smallest = min(available, key=lambda s: (s['size_bytes'], not 'english' in s['id'], s['id']))
            chosen = next(p for p in packages[family] if p.id == smallest['id'])
            row.update(package=chosen.id, size_bytes=smallest['size_bytes'])
            companions = []
            if family == 'auk':
                choices = [manager.package_size_record(by_id[i]) for i in ('auk_qwen_bf16', 'auk_qwen_q8_0')]
                valid = [s for s in choices if s['state'] == 'ok' and s['size_bytes'] is not None]
                if not valid:
                    raise manager.ManagerError('No accessible AuK conditioner')
                companions = [by_id[min(valid, key=lambda s: s['size_bytes'])['id']], by_id['auk_vae_f32']]
            elif family == 'f5_tts':
                companions = [by_id['vocos_mel_24khz']]
            row['companions'] = [p.id for p in companions]
            for companion in companions:
                size = manager.package_size_record(companion)
                if size['state'] != 'ok' or size['size_bytes'] is None:
                    raise manager.ManagerError('Unavailable companion: ' + companion.id)
                row['size_bytes'] += size['size_bytes']
            root = ROOT / 'models'
            # Leave space for staging plus the final package and working audio.
            if shutil.disk_usage(root).free < 2 * row['size_bytes'] + 1024**3:
                row['status'] = 'insufficient_free_space'
                save()
                continue
            options = SimpleNamespace(models_root=str(root), check=False, dry_run=False,
                                      overwrite=False, progress=False, cancel_file='')
            for package in [chosen] + companions:
                # Reuse pre-existing loose GGUFs without copying gigabytes.
                for remote in package.files:
                    target = root / package.target_directory / manager.stripped_path(remote, package.strip_prefix)
                    loose = root / Path(remote).name
                    if not target.exists() and loose.is_file() and loose.stat().st_size == manager.check_remote_file(package, remote).size:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.hardlink_to(loose)
                manager.install_package(package, records, options)
            row['status'] = 'installed'
        except OSError as error:
            # Network permission failures cannot be resolved by trying more files.
            row.update(status='network_or_io_error', error=str(error))
            save()
            print(str(error), file=sys.stderr)
            if '10013' in str(error):
                return 1
        except manager.ManagerError as error:
            row.update(status='package_error', error=str(error))
        save()
    report['complete'] = all(r['status'] in ('installed', 'not_in_installed_binary', 'no_published_gguf_package_in_local_spec')
                             for r in report['families'])
    save()
    return int(not report['complete'])


if __name__ == '__main__':
    raise SystemExit(main())
