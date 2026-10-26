"""Consistent online SQLite backup for native and container installations."""
import argparse
import os
from contextlib import closing
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

parser = argparse.ArgumentParser(description='Back up SQLite without stopping the service')
parser.add_argument('--data-dir', type=Path, default=Path('/app/data'),
                    help='Native server: /opt/etd/data; container default: /app/data')
root = parser.parse_args().data_dir.resolve()
source = root / 'console.sqlite3'
if not source.exists():
    raise SystemExit('Database not yet created; start the service first.')
backups = root / 'backups'
backups.mkdir(exist_ok=True)
stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S-%f')
target = backups / f'console-{stamp}.sqlite3'
temporary = target.with_suffix('.partial')
with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(temporary)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Backup verification failed.')
os.replace(temporary, target)
print(target)
