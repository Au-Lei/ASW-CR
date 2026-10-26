"""Double-click launcher: starts the console and opens the local browser."""
import importlib.util
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

root = Path(__file__).resolve().parent
if (root / '.runtime').is_dir():
    sys.path.insert(0, str(root / '.runtime'))

if __name__ == '__main__':
    missing = [name for name in ('flask', 'waitress', 'playwright', 'dotenv', 'bs4', 'requests')
               if importlib.util.find_spec(name) is None]
    if missing:
        print('缺少依赖，请在本目录执行：python -m pip install -r requirements.txt')
        input('按回车关闭…')
        raise SystemExit(1)

    # A second double-click opens the existing console instead of starting another worker.
    try:
        with socket.create_connection(('127.0.0.1', 8000), timeout=.5):
            webbrowser.open('http://127.0.0.1:8000')
            raise SystemExit(0)
    except OSError:
        pass

    def open_browser():
        for _ in range(50):
            time.sleep(.2)
            try:
                with socket.create_connection(('127.0.0.1', 8000), timeout=.2):
                    webbrowser.open('http://127.0.0.1:8000')
                    return
            except OSError:
                pass

    threading.Thread(target=open_browser, daemon=True).start()
    from etd_sync.web import main
    main()
