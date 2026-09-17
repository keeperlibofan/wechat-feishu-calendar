"""Loopback-only application server; no web framework or external assets required."""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .service import App


def serve(app, port):
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).parent / 'static'
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass

        def respond(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_bytes(body, 'application/json; charset=utf-8', status)

        def send_bytes(self, body, mime, status=200):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try: self.wfile.write(body)
            except BrokenPipeError: pass

        def secure(self, write=False):
            if self.headers.get('Host') not in hosts:
                self.respond({'error': '不允许的访问地址'}, 403); return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in hosts}:
                self.respond({'error': '不允许跨站访问'}, 403); return False
            if write and not secrets.compare_digest(self.headers.get('X-App-Token', ''), token):
                self.respond({'error': '页面已过期，请刷新后重试'}, 403); return False
            return True

        def do_GET(self):
            if not self.secure(): return
            parsed = urlsplit(self.path); path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == '/api/health': return self.respond({'ok': True})
                if path == '/api/bootstrap': return self.respond({'token': token})
                if path == '/api/state': return self.respond(app.state())
                if path == '/api/connections': return self.respond(app.connections(query.get('refresh') == ['1']))
                if path == '/api/groups/search': return self.respond({'groups': app.groups_available(query.get('q', [''])[0])})
                if path == '/api/auth/qr':
                    file = app.data_dir / 'auth.png'
                    if not file.exists(): return self.respond({'error': '请先发起授权'}, 404)
                    return self.send_bytes(file.read_bytes(), 'image/png')
                if path.startswith('/api/'): return self.respond({'error': '接口不存在'}, 404)
                name = 'index.html' if path == '/' else path.removeprefix('/')
                if name not in {'index.html', 'app.js', 'style.css', 'icon.svg'}: return self.respond({'error': '页面不存在'}, 404)
                self.send_bytes((assets / name).read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream')
            except Exception as exc: self.respond({'error': str(exc)}, 400)

        def do_POST(self):
            if not self.secure(write=True): return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if length < 0 or length > 300000: raise ValueError('请求过大')
                data = json.loads(self.rfile.read(length) or '{}')
                if not isinstance(data, dict): raise ValueError('请求格式无效')
                path = urlsplit(self.path).path
                if path == '/api/groups/add': result = app.add_group(data)
                elif path == '/api/groups/edit': result = app.edit_group(data['id'], data)
                elif path == '/api/groups/remove':
                    with app.publish_lock: app.db.execute('DELETE FROM groups WHERE id=?', (data['id'],))
                    result = {'ok': True}
                elif path == '/api/groups/preview': result = app.job('preview:' + data['id'], lambda: app.preview_group(data['id'], data.get('days', 3)))
                elif path == '/api/analyze': result = app.job('analyze', lambda: app.analyze(data['text'], data.get('received'), data.get('use_model', False)))
                elif path == '/api/events/stage': result = app.stage_manual(data)
                elif path == '/api/events/publish': result = app.job('publish:' + data['id'], lambda: app.publish(data['id'], data.get('edits'), data.get('target_event_id')))
                elif path == '/api/events/ignore':
                    with app.publish_lock: app.db.execute("UPDATE events SET state='ignored' WHERE id=? AND state IN ('pending','ready')", (data['id'],))
                    result = {'ok': True}
                elif path == '/api/messages/ignore':
                    app.db.execute("UPDATE messages SET state='ignored' WHERE id=?", (data['id'],)); result = {'ok': True}
                elif path == '/api/messages/retry': result = app.job('retry:' + data['id'], lambda: app.retry_message(data['id']))
                elif path == '/api/sync': result = app.job('sync', lambda: app.sync_once(force=True))
                elif path == '/api/auth/start': result = app.lark.auth_start()
                elif path == '/api/auth/finish':
                    def finish():
                        app.lark.auth_finish(); app.connections_cache = None
                        return app.connections(refresh=True)
                    result = app.job('auth', finish)
                elif path == '/api/settings':
                    interval, reminder = int(data.get('interval', 30)), int(data.get('reminder', 5))
                    if not 15 <= interval <= 600: raise ValueError('检查间隔须在 15–600 秒之间')
                    if reminder not in (0, 5, 10, 15, 30, 60): raise ValueError('请选择有效的提醒时间')
                    app.db.set('interval', interval); app.db.set('reminder', reminder)
                    app.db.set('model_enabled', bool(data.get('model_enabled', False))); result = {'ok': True}
                else: return self.respond({'error': '接口不存在'}, 404)
                self.respond(result)
            except Exception as exc: self.respond({'error': str(exc)}, 400)

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    actual_port = httpd.server_address[1]
    hosts.update({f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'})
    httpd.daemon_threads = True
    return httpd


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--data-dir', default=str(Path.home() / '.local/share/wechat-feishu-calendar'))
    parser.add_argument('--no-worker', action='store_true')
    args = parser.parse_args()
    app = App(args.data_dir)
    server = serve(app, args.port)
    if not args.no_worker: app.start()
    print(f'微信群日程助手已启动：http://127.0.0.1:{args.port}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: app.stop.set(); server.server_close()


if __name__ == '__main__': main()
