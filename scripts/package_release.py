"""Package portable source and demo assets; never include sessions, uploads or models."""
from pathlib import Path
import argparse
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.version import API_VERSION

excluded = {'.venv', '.install-tmp', 'node_modules', 'model-cache', 'runtime', 'test-runtime', '__pycache__', '.pytest_cache', '.git', '.agents'}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--suffix', default='', help='Optional release label, e.g. frontend-refresh')
args = parser.parse_args()
if args.suffix and not re.fullmatch(r'[a-z0-9-]+', args.suffix):
    parser.error('Suffix must contain lowercase letters, digits and hyphens only')
label = f'-{args.suffix}' if args.suffix else ''
target = ROOT.parent / f'product-card-v{API_VERSION}{label}.zip'
files = [p for p in ROOT.rglob('*') if p.is_file() and not excluded.intersection(p.relative_to(ROOT).parts)
         and (not p.name.startswith('.env') or p.name == '.env.example') and p.suffix not in {'.pyc', '.log', '.sqlite3'}]
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(files):
        archive.write(p, Path('product-card') / p.relative_to(ROOT))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert 'product-card/frontend/template-workbench.mjs' in names
    assert not any('/runtime/' in name or '/model-cache/' in name or '/.venv/' in name for name in names)
print(f'{target}\n{len(names)} files; {target.stat().st_size} bytes')
