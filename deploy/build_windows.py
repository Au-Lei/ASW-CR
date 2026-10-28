"""Build a Windows x64 portable bundle from an explicit, credential-free staging tree."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def private_bundle_file(relative):
    path = relative.as_posix().lower()
    # certifi's public trust store is required for HTTPS, and contains no private key.
    if path == '_internal/certifi/cacert.pem':
        return False
    return relative.name.lower() == '.env' or relative.suffix.lower() in ('.sqlite3', '.db', '.pem', '.key')


def stage_sources(stage):
    shutil.copytree(ROOT / 'etd_sync', stage / 'etd_sync',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'start_desktop.py', stage)
    shutil.copy2(ROOT / '.env.example', stage)
    (stage / 'wps').mkdir()
    shutil.copy2(ROOT / 'wps' / 'etd_bridge.js', stage / 'wps')


def build(commit):
    if sys.platform != 'win32':
        raise SystemExit('Windows EXE 必须在 Windows 环境构建，请使用 Windows desktop workflow')
    if sys.maxsize <= 2**32:
        raise SystemExit('请使用 64 位 Python')
    sys.path.insert(0, str(ROOT))
    from etd_sync.desktop import tray_image

    build_dir, release = ROOT / 'build', ROOT / 'release'
    build_dir.mkdir(exist_ok=True)
    release.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='windows-stage-', dir=build_dir) as temporary:
        stage = Path(temporary)
        stage_sources(stage)
        icon = stage / 'app.ico'
        tray_image().save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                   '--onedir', '--windowed', '--name', 'ASW-CR', '--icon', str(icon),
                   '--distpath', str(release / 'windows'),
                   '--workpath', str(build_dir / 'windows-work'),
                   '--specpath', str(build_dir / 'windows-spec'),
                   '--collect-all', 'playwright', '--hidden-import', 'pystray._win32',
                   '--exclude-module', 'pystray._darwin', '--exclude-module', 'pystray._xorg',
                   '--exclude-module', 'pystray._appindicator']
        for source, destination in [('etd_sync/templates', 'etd_sync/templates'),
                                    ('etd_sync/static', 'etd_sync/static'),
                                    ('.env.example', '.'), ('wps', 'wps')]:
            command.extend(['--add-data', str(stage / source) + ':' + destination])
        command.append(str(stage / 'start_desktop.py'))
        env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': '0'}
        subprocess.run(command, cwd=stage, env=env, check=True)

    bundle = release / 'windows' / 'ASW-CR'
    shutil.copyfile(ROOT / 'docs' / 'WINDOWS.md', bundle / '使用说明.txt')
    shutil.copyfile(ROOT / 'wps' / 'etd_bridge.js', bundle / 'WPS对接脚本.txt')
    info = {'version': '0.3.0', 'commit': commit, 'platform': 'windows-x64',
            'packages': {name: importlib.metadata.version(name)
                         for name in ('PyInstaller', 'playwright', 'Flask', 'waitress', 'pystray', 'Pillow')}}
    (bundle / 'build-info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    archive = release / 'ASW-CR-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(bundle.rglob('*')):
            if not path.is_file():
                continue
            if private_bundle_file(path.relative_to(bundle)):
                raise RuntimeError('发布目录包含不应分发的配置或业务文件：' + path.name)
            output.write(path, Path('ASW-CR') / path.relative_to(bundle))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / 'ASW-CR-Windows-x64.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
    print('Created', archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', default='local')
    build(parser.parse_args().commit)
