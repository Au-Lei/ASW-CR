import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class BackupTests(unittest.TestCase):
    def test_native_backup_with_active_wal_database(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            with closing(sqlite3.connect(data / 'console.sqlite3')) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('CREATE TABLE sample (value TEXT)')
                connection.execute("INSERT INTO sample VALUES ('committed test row')")
                connection.commit()
                result = subprocess.run([sys.executable, str(ROOT / 'deploy' / 'backup.py'),
                                         '--data-dir', directory], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshots = list((data / 'backups').glob('*.sqlite3'))
                self.assertEqual(len(snapshots), 1)
                with closing(sqlite3.connect(snapshots[0])) as backup:
                    self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(backup.execute('SELECT value FROM sample').fetchone()[0], 'committed test row')

    def test_missing_database_does_not_create_empty_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'deploy' / 'backup.py'),
                                     '--data-dir', directory], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(directory) / 'console.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
