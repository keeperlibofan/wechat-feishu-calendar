"""Read only the selected group's source data, using the user's existing wechat-cli.

Run with that checkout's Python to preserve its crypto/zstd dependencies.
Decryption caches are isolated from the existing auto-reply application.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing

os.umask(0o077)
checkout = Path(os.environ.get('WECHAT_CLI_DIR', str(Path.home() / '文档/wechat/wechat-cli')))
sys.path.insert(0, str(checkout))


def main(request):
    from wechat_cli.core.db_cache import DBCache
    private = Path(os.environ['CALENDAR_APP_DATA']) / 'wechat-cache'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    DBCache.CACHE_DIR = str(private)
    DBCache.MTIME_FILE = str(private / '_mtimes.json')
    from wechat_cli.core.context import AppContext
    from wechat_cli.core.contacts import get_contact_names, get_contact_full
    from wechat_cli.core.messages import decompress_content, _parse_message_content
    app = AppContext()
    names = get_contact_names(app.cache, app.decrypted_dir)
    if request['action'] == 'groups':
        groups = {}
        for item in get_contact_full(app.cache, app.decrypted_dir):
            username = item.get('username', '')
            if username.endswith('@chatroom'):
                groups[username] = {'id': username, 'name': item.get('remark') or item.get('nick_name') or username, 'last_message_at': 0}
        path = app.cache.get('session/session.db')
        if path:
            with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as conn:
                for username, ts in conn.execute("SELECT username,last_timestamp FROM SessionTable WHERE username LIKE '%@chatroom'"):
                    groups[username] = {'id': username, 'name': names.get(username) or groups.get(username, {}).get('name') or username, 'last_message_at': ts or 0}
        query = request.get('query', '').casefold()
        return sorted([g for g in groups.values() if query in (g['name'] + g['id']).casefold()], key=lambda g: -g['last_message_at'])
    if request['action'] != 'messages': raise ValueError('未知的读取操作')
    username = str(request['group_id'])
    if not username.endswith('@chatroom') or len(username) > 100: raise ValueError('请选择真实的微信群')
    table = 'Msg_' + hashlib.md5(username.encode()).hexdigest()
    cursor = request.get('cursor') or [int(request.get('since', 0)), '', 0]
    size = max(1, min(int(request.get('limit', 250)), 500))
    rows = []
    for key in sorted(app.msg_db_keys):
        path = app.cache.get(key)
        if not path: raise RuntimeError('微信消息数据库暂不可读，请保持微信登录后重试')
        with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as conn:
            if not conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone(): continue
            if key < cursor[1]: clause, params = 'create_time > ?', [cursor[0]]
            elif key == cursor[1]: clause, params = '(create_time > ? OR (create_time=? AND local_id>?))', [cursor[0], cursor[0], cursor[2]]
            else: clause, params = 'create_time >= ?', [cursor[0]]
            query = f'SELECT local_id,server_id,local_type,create_time,message_content,WCDB_CT_message_content FROM [{table}] WHERE {clause} ORDER BY create_time,local_id LIMIT ?'
            for local_id, server_id, kind, ts, content, ct in conn.execute(query, (*params, size + 1)):
                body = decompress_content(content, ct) or ''
                sender, body = _parse_message_content(body, kind, True)
                base_type = int(kind) & 0xFFFFFFFF
                # Never guess an image by selecting a random file from an attachment directory.
                if base_type != 1:
                    body = '[图片通知：请复制文字后导入]' if base_type == 3 else ''
                raw = f'{username}|{server_id}' if server_id else f'{username}|{key}|{local_id}|{ts}'
                rows.append({'id': hashlib.sha256(raw.encode()).hexdigest(), 'text': str(body), 'timestamp': ts,
                             'sender': names.get(sender, sender), 'type': 'text' if base_type == 1 else ('image' if base_type == 3 else 'other'),
                             'cursor': [ts, key, local_id]})
    rows.sort(key=lambda x: x['cursor'])
    page = rows[:size]
    return {'messages': page, 'cursor': page[-1]['cursor'] if page else cursor, 'has_more': len(rows) > size}


if __name__ == '__main__':
    try:
        data = main(json.load(sys.stdin))
        print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)
