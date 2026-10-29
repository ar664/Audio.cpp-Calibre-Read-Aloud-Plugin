"""Install one GGUF package from audio.cpp's bundled model manager."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'bin/tools'))
import model_manager_v2 as manager

parser = argparse.ArgumentParser()
parser.add_argument('package')
parser.add_argument('--target-directory')
args = parser.parse_args()
specs = manager.load_specs(root / 'bin/model_specs')
records = manager.flatten_packages(specs)
package = next(p for p in records if p.id == args.package)
if args.target_directory:
    package = replace(package, target_directory=args.target_directory)
    records = [package if p.id == package.id else p for p in records]
options = SimpleNamespace(models_root=str(root / 'models'), check=False, dry_run=False,
                          overwrite=False, progress=False, cancel_file='')
manager.install_package(package, records, options)
