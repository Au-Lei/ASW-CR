"""Single-instance lock and local-only HTTP server lifecycle."""
import json
import os
import threading
import time
import urllib.request
import uuid


class InstanceLock:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def read_json(url):
    # A corporate proxy must not receive localhost requests or instance metadata.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.load(response)


def existing_url(runtime_file, attempts=10):
    for _ in range(attempts):
        try:
            record = json.loads(runtime_file.read_text(encoding='utf-8'))
            port = record['port']
            identifier = record['instance_id']
            if (type(port) is not int or not 1 <= port <= 65535 or
                    not isinstance(identifier, str) or len(identifier) != 32):
                return None
            url = f'http://127.0.0.1:{port}'
            health = read_json(url + '/api/health')
            if isinstance(health, dict) and health.get('app') == 'ASW-CR' and health.get('instance_id') == identifier:
                return url
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(.2)
    return None


class LocalServer:
    def __init__(self, config, console=None):
        from waitress import create_server
        from .web import create_app

        self.instance_id = uuid.uuid4().hex
        self.app = create_app(config=config, console=console, instance_id=self.instance_id)
        self.console = self.app.extensions['console']
        self.server = create_server(self.app, host='127.0.0.1', port=0, threads=6,
                                    asyncore_loop_timeout=.1)
        self.port = int(self.server.effective_port)
        self.url = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.server.run, name='desktop-http', daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(50):
            try:
                health = read_json(self.url + '/api/health')
                if health.get('instance_id') == self.instance_id:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        raise RuntimeError('本地服务未能启动')

    def publish(self, runtime_file):
        temporary = runtime_file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'port': self.port, 'instance_id': self.instance_id}), encoding='utf-8')
        os.replace(temporary, runtime_file)

    def close(self):
        from waitress import wasyncore
        self.server.close()
        wasyncore.close_all(map=self.server._map, ignore_all=True)
        self.server.task_dispatcher.shutdown()
        if self.thread.is_alive():
            self.thread.join(timeout=2)
