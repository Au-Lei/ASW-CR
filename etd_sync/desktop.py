"""Windows tray application. Importing this module never opens a window."""
import argparse
import json
import logging
import os
import subprocess
import sys
import webbrowser

from .desktop_config import configure, read_config, validate_config
from .desktop_runtime import InstanceLock, LocalServer, existing_url
from .paths import app_paths

TITLE = '长荣货物追踪'


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), (0, 21, 41, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill='#096dce')
    draw.line((16, 37, 48, 37, 42, 47, 22, 47, 16, 37), fill='white', width=3)
    draw.line((26, 34, 26, 21, 38, 21, 38, 34), fill='white', width=3)
    return image


def notice(message, error=False):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10 if error else 0x40)


class DesktopApp:
    def __init__(self, root, paths, config):
        import pystray
        from .service import Console
        self.root, self.paths = root, paths
        self.runtime_file = paths.home / 'instance.json'
        self.server = LocalServer(config, console=Console(paths.database, config))
        self.icon = pystray.Icon('ASW-CR', tray_image(), TITLE, menu=pystray.Menu(
            pystray.MenuItem('打开控制台', self.schedule(self.open_browser), default=True),
            pystray.MenuItem('修改 WPS 配置', self.schedule(self.settings)),
            pystray.MenuItem('打开数据目录', self.schedule(self.open_data)),
            pystray.MenuItem('查看 WPS 对接脚本', self.schedule(self.open_bridge)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出程序', self.schedule(self.quit)),
        ))
        self.stopped = False

    def schedule(self, action):
        return lambda icon, item: self.root.after(0, action)

    def open_browser(self):
        webbrowser.open(self.server.url)

    def open_data(self):
        os.startfile(self.paths.home)

    def open_bridge(self):
        # .js has an executable Windows association; explicitly use a text editor.
        subprocess.Popen(['notepad.exe', str(self.paths.resources / 'wps' / 'etd_bridge.js')])

    def settings(self):
        from tkinter import messagebox
        service = self.server.console
        if not service.lock.acquire(blocking=False):
            messagebox.showinfo(TITLE, '正在同步，请等待任务完成后修改配置。', parent=self.root)
            return
        try:
            config = configure(self.root, self.paths.config)
            if config is not None:
                # The WPS factory captures this same dict; no second Console is created.
                service.config.update(config)
                messagebox.showinfo(TITLE, '配置已保存。请回到网页读取订单以刷新表格数据。', parent=self.root)
        finally:
            service.lock.release()

    def quit(self):
        from tkinter import messagebox
        if not self.server.console.lock.acquire(blocking=False):
            messagebox.showinfo(TITLE, '同步任务正在执行，请等待完成后再退出，避免中断写回。', parent=self.root)
            return
        self.close()
        self.root.quit()

    def close(self):
        if self.stopped:
            return
        self.stopped = True
        self.server.close()
        self.icon.stop()
        self.runtime_file.unlink(missing_ok=True)

    def run(self):
        self.server.start()
        self.server.publish(self.runtime_file)
        self.icon.run_detached()
        self.open_browser()
        self.root.mainloop()


def run_desktop():
    import tkinter as tk
    paths = app_paths(desktop=True)
    paths.home.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(paths.home / 'desktop.lock')
    if not lock.acquire():
        url = existing_url(paths.home / 'instance.json')
        if url:
            webbrowser.open(url)
        else:
            notice('程序已经启动，可能正在等待填写配置。请查看配置窗口或任务栏托盘图标。')
        return 0
    root, app = None, None
    try:
        root = tk.Tk()
        root.withdraw()
        config = read_config(paths.config)
        try:
            config = validate_config(config)
        except ValueError:
            config = configure(root, paths.config)
            if config is None:
                return 0
        app = DesktopApp(root, paths, config)
        try:
            app.run()
        finally:
            app.close()
        return 0
    finally:
        if root is not None:
            root.destroy()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument('--self-test', metavar='RESULT_JSON', help='离线安装包自检，不使用正式配置')
    args = parser.parse_args()
    if getattr(sys, 'frozen', False):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
    if args.self_test:
        from .desktop_check import self_test
        try:
            result = self_test()
        except Exception:
            import traceback
            result = {'ok': False, 'error': traceback.format_exc()}
        from pathlib import Path
        Path(args.self_test).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0 if result['ok'] else 1
    if sys.platform != 'win32':
        raise SystemExit('桌面版入口仅用于 Windows；本机开发请运行 start_web.py')
    paths = app_paths(desktop=True)
    log = paths.home / 'logs' / 'desktop.log'
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log, encoding='utf-8', level=logging.INFO,
                            format='%(asctime)s %(levelname)s %(message)s')
        return run_desktop()
    except Exception:
        logging.exception('Desktop startup failed')
        notice('启动失败。请检查程序是否完整解压，以及数据目录是否可写。\n诊断日志：' + str(log), error=True)
        return 1
