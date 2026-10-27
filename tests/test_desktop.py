import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from deploy.build_windows import stage_sources
from etd_sync.desktop import DesktopApp
from etd_sync.desktop_config import DEFAULTS, read_config, save_config, validate_config
from etd_sync.desktop_runtime import InstanceLock, existing_url
from etd_sync.paths import app_paths


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = {**DEFAULTS, 'WPS_WEBHOOK_URL':
            'https://www.kdocs.cn/api/v3/ide/file/demo/script/demo/sync_task',
            'WPS_API_TOKEN': 'test-token', 'DATE_YEAR': '2026'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_frozen_paths_use_user_data_not_bundled_resources(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.home)}, clear=True), \
                patch('etd_sync.paths.sys.frozen', True, create=True):
            paths = app_paths()
            self.assertEqual(paths.home, self.home / 'ASW-CR')
            self.assertNotEqual(paths.home, paths.resources)
            self.assertEqual(paths.database, paths.home / 'data' / 'console.sqlite3')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(app_paths().home, app_paths().resources)

    def test_explicit_home_supports_unicode_and_spaces(self):
        home = self.home / '中文 用户目录'
        with patch.dict(os.environ, {'ETD_HOME': str(home)}):
            self.assertEqual(app_paths().config, home.resolve() / '.env')

    def test_config_round_trip_and_invalid_save_preserve_existing_file(self):
        config = {**self.config, 'WPS_API_TOKEN': 'quote\'"slash\\dollar${DO_NOT_EXPAND}',
                  'WPS_SHEET_NAME': '业务订单'}
        path = self.home / '配置目录' / '.env'
        save_config(path, config)
        self.assertEqual(read_config(path)['WPS_API_TOKEN'], config['WPS_API_TOKEN'])
        self.assertEqual(read_config(path)['WPS_SHEET_NAME'], '业务订单')
        previous = path.read_bytes()
        for invalid in ({'WPS_API_TOKEN': ''}, {'DATE_YEAR': 'bad'},
                        {'QUERY_INTERVAL_SECONDS': 'nan'}, {'WPS_SHEET_NAME': 'bad\nname'}):
            with self.assertRaises(ValueError):
                save_config(path, {**config, **invalid})
            self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(list(path.parent.glob('.settings-*')), [])

    def test_single_instance_lock_excludes_other_process_and_releases(self):
        path = self.home / 'desktop.lock'
        first = InstanceLock(path)
        self.assertTrue(first.acquire())
        code = ('from pathlib import Path; from etd_sync.desktop_runtime import InstanceLock; '
                'import sys; lock=InstanceLock(Path(sys.argv[1])); print(lock.acquire()); lock.close()')
        try:
            result = subprocess.check_output([sys.executable, '-c', code, str(path)], text=True)
            self.assertEqual(result.strip(), 'False')
        finally:
            first.close()
        result = subprocess.check_output([sys.executable, '-c', code, str(path)], text=True)
        self.assertEqual(result.strip(), 'True')

    def test_existing_instance_requires_matching_identity(self):
        path = self.home / 'instance.json'
        identifier = 'a' * 32
        path.write_text(json.dumps({'port': 12345, 'instance_id': identifier}), encoding='utf-8')
        with patch('etd_sync.desktop_runtime.time.sleep'), \
                patch('etd_sync.desktop_runtime.read_json') as read:
            read.return_value = {'app': 'ASW-CR', 'instance_id': identifier}
            self.assertEqual(existing_url(path, attempts=1), 'http://127.0.0.1:12345')
            read.return_value = {'app': 'ASW-CR', 'instance_id': 'different'}
            self.assertIsNone(existing_url(path, attempts=1))
            read.return_value = []
            self.assertIsNone(existing_url(path, attempts=1))

    def test_exit_refuses_running_job_then_blocks_new_jobs_while_stopping(self):
        app = DesktopApp.__new__(DesktopApp)
        lock = threading.Lock()
        app.server = Mock(console=Mock(lock=lock))
        app.root, app.close = Mock(), Mock()
        tkinter = types.ModuleType('tkinter')
        tkinter.messagebox = Mock()
        with patch.dict(sys.modules, {'tkinter': tkinter}):
            lock.acquire()
            app.quit()
            app.close.assert_not_called()
            app.root.quit.assert_not_called()
            lock.release()
            app.quit()
            app.close.assert_called_once()
            app.root.quit.assert_called_once()
            self.assertTrue(lock.locked())

    def test_build_staging_excludes_private_files(self):
        stage = self.home / 'staging'
        stage.mkdir()
        stage_sources(stage)
        files = list(stage.rglob('*'))
        self.assertFalse(any(p.name == '.env' or p.suffix in ('.sqlite3', '.db') for p in files))
        self.assertFalse(any('__pycache__' in p.parts for p in files))
        self.assertTrue((stage / '.env.example').is_file())
        self.assertTrue((stage / 'etd_sync' / 'static' / 'console-model.mjs').is_file())
        self.assertTrue((stage / 'wps' / 'etd_bridge.js').is_file())


if __name__ == '__main__':
    unittest.main()
