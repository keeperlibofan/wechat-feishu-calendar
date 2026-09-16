"""Documentation-only demo using temporary storage and simulated integrations.

Run from the repository root: python3 docs/tools/demo.py
No worker, real messages, credentials or external writes are used.
"""
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.__main__ import serve
from app.service import App


CALENDARS = [
    {'id': 'demo-career', 'name': '求职日历', 'writable': True, 'primary': True},
    {'id': 'demo-research', 'name': '科研日历', 'writable': True, 'primary': False},
    {'id': 'demo-campus', 'name': '校园日历', 'writable': True, 'primary': False},
]
GROUPS = [
    {'id': 'demo-career@chatroom', 'name': '校园招聘通知'},
    {'id': 'demo-research@chatroom', 'name': '课题组讨论'},
    {'id': 'demo-campus@chatroom', 'name': '研一班级通知'},
]


class DemoSource:
    def call(self, action, **params):
        if action == 'groups':
            return GROUPS
        return {'messages': [], 'cursor': params.get('cursor', []), 'has_more': False}

    def fingerprint(self):
        return 'documentation-demo', 'documentation-demo'


class DemoLark:
    def canonical(self, value):
        return 'demo-career' if value == 'primary' else value

    def identity(self):
        return {'name': '演示账号', 'account': 'demo', 'profile': 'demo',
                'available': True, 'status': 'ready'}

    def calendars(self):
        return CALENDARS

    def create(self, *args, **kwargs):
        raise RuntimeError('文档演示不支持写入飞书')

    update = create
    auth_start = create
    auth_finish = create


class DemoApp(App):
    def connections(self, refresh=False):
        return {'wechat': {'ok': True, 'groups': 3, 'message': '演示连接'},
                'lark': {'ok': True, **self.lark.identity()},
                'model': {'available': False, 'model': '', 'url': ''},
                'calendars': CALENDARS}

    def analyze(self, text, received=None, use_model=False):
        if use_model:
            raise RuntimeError('文档演示不调用模型服务')
        return super().analyze(text, received, False)


def seed(app):
    now = time.time()
    for index, group in enumerate(GROUPS):
        app.add_group({**group, 'calendar_id': CALENDARS[index]['id'],
                       'enabled': index < 2, 'mode': 'review' if index == 2 else 'auto'})
    app.db.execute('UPDATE groups SET last_scan=?', (now,))
    app.db.set('primary_calendar_id', 'demo-career')
    app.runtime.update(last_check=now)
    rows = [
        ('智行科技校园招聘宣讲会', '09:30', '10:30', '科教楼 A106', 0, 'synced'),
        ('智行科技校园招聘双选会', '10:30', '12:00', '科教楼 A103', 0, 'synced'),
        ('课题组每周进展交流', '14:00', '15:30', '实验室 302', 1, 'synced'),
        ('研究生学术分享会', '16:00', '17:00', '报告厅 B201', 1, 'synced'),
        ('学院迎新志愿者说明会', '18:00', '19:00', '学生活动中心', 2, 'pending'),
        ('课题组讨论时间调整', '15:00', '16:00', '实验室 302', 1, 'pending'),
        ('智行科技校园招聘宣讲会', '09:30', '10:30', '科教楼 A106', 0, 'duplicate'),
    ]
    for index, (title, start, end, location, group, state) in enumerate(rows):
        event = {'title': title, 'start': f'2026-09-18T{start}:00+08:00',
                 'end': f'2026-09-18T{end}:00+08:00', 'location': location,
                 'description': '此内容为文档展示用的虚构通知。'}
        reasons = ['示例：请核对通知中的最终安排'] if state == 'pending' else []
        app.db.execute('''INSERT INTO events
            (id,message_id,group_id,calendar_id,calendar_name,payload,state,reasons,created,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (f'demo-{index}', f'demo-message-{index}', GROUPS[group]['id'],
             CALENDARS[group]['id'], CALENDARS[group]['name'],
             json.dumps(event, ensure_ascii=False), state, json.dumps(reasons), now, now-index))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='qunli-docs-') as data:
        app = DemoApp(data, source=DemoSource(), lark=DemoLark())
        seed(app)
        server = serve(app, 8767)
        print('Documentation demo: http://127.0.0.1:8767', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
