"""Build an initial-deployment zip, including a consistent DB snapshot, no tokens."""
from contextlib import closing
import sqlite3
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
release = ROOT / 'release'
release.mkdir(exist_ok=True)
archive = release / 'etd-server.zip'
files = [ROOT / name for name in ('Dockerfile','compose.yaml','.dockerignore','requirements.txt','.env.example','README.md')]
files += [p for folder in ('etd_sync','deploy','docs') for p in (ROOT/folder).rglob('*')
          if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc',)
          and p.name != 'cloud-server.local']
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
    for path in files:
        bundle.write(path,path.relative_to(ROOT).as_posix())
    source = ROOT/'data'/'console.sqlite3'
    if source.exists():
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp)/'console.sqlite3'
            with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True)) as src:
                with closing(sqlite3.connect(snapshot)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise SystemExit('Database integrity check failed.')
            bundle.write(snapshot,'data/console.sqlite3')
print(f'Created {archive}; includes existing database snapshot, excludes .env credentials.')
