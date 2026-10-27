"""HTTP routes and the local Waitress entry point."""
import argparse
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Preserve existing imports: from etd_sync.web import Console.
from .service import Console
from .paths import app_paths

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None, console=None, instance_id=None):
    paths = app_paths()
    if config is None:
        load_dotenv(paths.config)
        config = dict(os.environ)
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
    app.config['TRUSTED_HOSTS'] = ['127.0.0.1', 'localhost', '[::1]']
    csrf = secrets.token_urlsafe(32)
    service = console or Console(paths.database, config)
    app.extensions['console'] = service

    @app.after_request
    def headers(response):
        # Windows registry MIME associations may classify JS modules as text/plain.
        if request.endpoint == 'static' and request.path.endswith(('.js', '.mjs')):
            response.mimetype = 'text/javascript'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return render_template('index.html', csrf=csrf)

    @app.get('/api/state')
    def state():
        return jsonify(service.snapshot())

    @app.get('/api/health')
    def health():
        return jsonify(app='ASW-CR', instance_id=instance_id)

    @app.post('/api/jobs')
    def start():
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token', '').encode('utf-8'),
                                      csrf.encode('utf-8')):
            return jsonify(error='页面已过期，请刷新后重试'), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='请求必须是 JSON 对象'), 400
        mode = payload.get('mode')
        if mode not in ('read', 'sync'):
            return jsonify(error='未知操作'), 400
        try:
            if 'order_nos' in payload and payload['order_nos'] is None:
                raise ValueError('请选择至少一票有效订单')
            return jsonify(id=service.start(mode, payload.get('order_nos'))), 202
        except ValueError as exc:
            return jsonify(error=service.error(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=service.error(exc)), 409

    return app


def main():
    parser = argparse.ArgumentParser(description='长荣船期同步网页控制台')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1', help='容器内部可设为 0.0.0.0，主机发布仍限制本机')
    args = parser.parse_args()
    from waitress import serve
    print(f'管理界面：http://127.0.0.1:{args.port} （关闭窗口即停止服务）', flush=True)
    serve(create_app(), host=args.host, port=args.port, threads=6)


if __name__ == '__main__':
    main()
