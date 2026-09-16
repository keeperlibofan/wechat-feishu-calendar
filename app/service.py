from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
from .adapters import IntegrationError, Lark, WeChat, model_config, model_extract
from .extractor import extract, received_time, validate_event
from .store import Store


def event_fingerprint(event):
    clean = lambda s: re.sub(r'[\s\W_]+', '', str(s)).casefold()
    key = [clean(event['title']), received_time(event['start']).isoformat(), received_time(event['end']).isoformat(), clean(event.get('location', ''))]
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()


class App:
    def __init__(self, data_dir, source=None, lark=None):
        self.data_dir = Path(data_dir)
        self.db = Store(self.data_dir / 'app.db')
        self.source = source or WeChat(self.data_dir)
        self.lark = lark or Lark(self.data_dir)
        self.sync_lock = threading.Lock()
        self.publish_lock = threading.RLock()
        self.stop = threading.Event()
        self.last_fingerprint = ''
        self.more_pending = False
        self.runtime = {'state': 'idle', 'last_check': None, 'error': ''}
        self.connections_cache = None
        self.connections_at = 0
        self.group_cache, self.group_cache_at = [], 0
        self.jobs = {}
        # A crash between remote success and local commit must retry with the same key.
        self.db.execute("UPDATE events SET state='error',error='上次同步被中断，可安全重试' WHERE state='syncing'")

    def groups_available(self, query='', refresh=False):
        if refresh or time.time() - self.group_cache_at > 120:
            self.group_cache = self.source.call('groups', query='')
            self.group_cache_at = time.time()
        return [x for x in self.group_cache if query.casefold() in (x['name'] + x['id']).casefold()][:300]

    def connections(self, refresh=False):
        if self.connections_cache and not refresh and time.time() - self.connections_at < 60:
            return self.connections_cache
        status = {'wechat': {}, 'lark': {}, 'model': model_config(), 'calendars': []}
        try:
            groups = self.groups_available(refresh=refresh)
            status['wechat'] = {'ok': True, 'groups': len(groups), 'message': '已连接本机微信'}
        except Exception as exc: status['wechat'] = {'ok': False, 'message': str(exc)}
        try:
            identity = self.lark.identity()
            if not identity['available']: raise IntegrationError('请先登录飞书用户身份')
            binding = identity['profile'] + ':' + identity['account']
            old = self.db.get('lark_account')
            if old and old != binding: raise IntegrationError('飞书账号已切换，已暂停写入，请切回原账号', 'account_changed')
            if not old: self.db.set('lark_account', binding)
            status['lark'] = {'ok': True, **identity}
            try:
                status['calendars'] = self.lark.calendars()
            except IntegrationError as exc:
                status['lark'].update(calendar_error=str(exc), needs_auth=exc.code == 'missing_scope')
                status['calendars'] = [{'id': 'primary', 'name': identity['name'] + ' · 主日历', 'writable': True, 'primary': True}]
        except Exception as exc: status['lark'] = {'ok': False, 'message': str(exc)}
        self.connections_cache, self.connections_at = status, time.time()
        return status

    def calendar(self, calendar_id):
        for item in self.connections()['calendars']:
            if item['id'] == calendar_id and item.get('writable'): return item
        raise ValueError('请选择你有写入权限的飞书日历')

    def canonical_calendar(self, calendar_id):
        resolved = self.lark.canonical(calendar_id)
        return self.db.get('primary_calendar_id', 'primary') if resolved == 'primary' else resolved

    def add_group(self, data):
        group = next((g for g in self.groups_available() if g['id'] == data['id']), None)
        if not group: raise ValueError('没有找到这个微信群，请重新搜索')
        target = self.calendar(data['calendar_id'])
        now = int(time.time())
        mode = data.get('mode', 'auto')
        if mode not in ('auto', 'review'): raise ValueError('同步方式无效')
        self.db.execute('''INSERT INTO groups(id,name,calendar_id,calendar_name,enabled,mode,since,cursor,created)
            VALUES(?,?,?,?,?,?,?,?,?)''', (group['id'], group['name'], target['id'], target['name'],
                int(bool(data.get('enabled', False))), mode, now, json.dumps([now, '', 0]), now))
        self.last_fingerprint = ''
        return group

    def edit_group(self, group_id, data):
        with self.publish_lock:
            group = self.db.one('SELECT * FROM groups WHERE id=?', (group_id,))
            if not group: raise ValueError('同步群不存在')
            target = self.calendar(data.get('calendar_id', group['calendar_id']))
            mode = data.get('mode', group['mode'])
            if mode not in ('auto', 'review'): raise ValueError('同步方式无效')
            self.db.execute('UPDATE groups SET calendar_id=?,calendar_name=?,enabled=?,mode=? WHERE id=?',
                (target['id'], target['name'], int(bool(data.get('enabled', group['enabled']))), mode, group_id))
        self.last_fingerprint = ''
        return {'ok': True}

    def state(self):
        events = self.db.events()
        issues = self.db.rows("SELECT m.*,g.name AS group_name FROM messages m LEFT JOIN groups g ON g.id=m.group_id WHERE m.state IN ('review','error') ORDER BY m.created DESC LIMIT 60")
        counts = {r['state']: r['n'] for r in self.db.rows('SELECT state,COUNT(*) n FROM events GROUP BY state')}
        groups = self.db.rows('SELECT * FROM groups ORDER BY created')
        return {'groups': groups, 'events': events, 'issues': issues, 'counts': counts, 'runtime': self.runtime.copy(),
                'settings': {'interval': self.db.get('interval', 30), 'reminder': self.db.get('reminder', 5),
                             'model_enabled': self.db.get('model_enabled', False)},
                'jobs': self.jobs, 'timezone': 'Asia/Shanghai', 'primary_calendar_id': self.db.get('primary_calendar_id')}

    def analyze(self, text, received=None, use_model=False):
        if use_model and not self.db.get('model_enabled', False): raise ValueError('请先在连接设置中启用模型识别')
        return model_extract(text, received) if use_model else extract(text, received)

    def stage(self, message, group, result, history=False):
        now = time.time()
        for index, event in enumerate(result['events']):
            event_id = hashlib.sha256((message['id'] + ':' + str(index)).encode()).hexdigest()[:32]
            reasons = list(event.get('reasons', []))
            if history: reasons.append('历史消息，确认后添加')
            try:
                validate_event(event)
                if received_time(event['end']).timestamp() <= now: reasons.append('活动已结束')
                if received_time(event['start']).timestamp() > now + 366 * 86400: reasons.append('活动超过一年，请核对日期')
            except (ValueError, KeyError): reasons.append('日期或时间需要补充')
            # A same-title notification changing time/location must not silently become a second event.
            for old in self.db.events(500):
                if old['state'] == 'synced' and self.canonical_calendar(old['calendar_id']) == self.canonical_calendar(group['calendar_id']) and old['event']['title'] == event['title']:
                    if old['event'].get('start', '')[:10] == event.get('start', '')[:10] and event_fingerprint(old['event']) != event_fingerprint(event):
                        reasons.append('已有同名日程，可能是时间或地点变更'); break
            automatic = not history and group.get('enabled') and group.get('mode') == 'auto' and not reasons
            description = f"来源微信群：{group['name']}\n消息时间：{received_time(message['timestamp']).strftime('%Y-%m-%d %H:%M')}\n\n" + event.get('description', message.get('text', ''))
            event['description'] = description[:12000]
            self.db.execute('''INSERT OR IGNORE INTO events(id,message_id,group_id,calendar_id,calendar_name,payload,state,reasons,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (event_id, message['id'], group.get('id'), group['calendar_id'], group['calendar_name'],
                json.dumps(event, ensure_ascii=False), 'ready' if automatic else 'pending', json.dumps(list(dict.fromkeys(reasons)), ensure_ascii=False), now, now))
        return len(result['events'])

    def process_message(self, message, group):
        if message['type'] == 'image':
            self.db.execute("UPDATE messages SET state='review',error='图片消息暂不能可靠定位原图；请在识别工作台粘贴图片中的文字' WHERE id=?", (message['id'],))
            return
        if message['type'] != 'text' or not message['text'].strip():
            self.db.execute("UPDATE messages SET state='ignored' WHERE id=?", (message['id'],)); return
        try:
            result = extract(message['text'], message['timestamp'])
            if result['issues'] and not result['events'] and self.db.get('model_enabled', False):
                result = model_extract(message['text'], message['timestamp'])
            self.stage(message, group, result)
            state = 'review' if result['issues'] and not result['events'] else ('done' if result['events'] else 'ignored')
            self.db.execute('UPDATE messages SET state=?,error=? WHERE id=?', (state, '；'.join(result['issues']), message['id']))
        except Exception as exc:
            self.db.execute("UPDATE messages SET state='error',error=? WHERE id=?", (str(exc)[:800], message['id']))

    def sync_once(self, force=False):
        if not self.sync_lock.acquire(blocking=False): return {'busy': True}
        self.runtime.update(state='running', error='')
        try:
            groups = self.db.rows('SELECT * FROM groups WHERE enabled=1')
            if not groups: return {'groups': 0, 'messages': 0}
            fingerprint, source_account = self.source.fingerprint()
            old_source = self.db.get('wechat_source')
            if old_source and old_source != source_account: raise IntegrationError('微信账号或数据库路径发生变化，请核对后重新添加同步群')
            if not old_source: self.db.set('wechat_source', source_account)
            total, more = 0, False
            if force or self.more_pending or fingerprint != self.last_fingerprint:
                for group in groups:
                    try:
                        cursor = json.loads(group['cursor'])
                        for _ in range(10):
                            result = self.source.call('messages', group_id=group['id'], cursor=cursor, limit=250)
                            with self.db.connect() as db:
                                for msg in result['messages']:
                                    db.execute('INSERT OR IGNORE INTO messages(id,group_id,text,timestamp,sender,type,created) VALUES(?,?,?,?,?,?,?)',
                                        (msg['id'], group['id'], msg['text'], msg['timestamp'], msg['sender'], msg['type'], time.time()))
                                db.execute("UPDATE groups SET cursor=?,last_scan=?,last_error='' WHERE id=?", (json.dumps(result['cursor']), time.time(), group['id']))
                            total += len(result['messages'])
                            if not result['has_more']: break
                            if result['cursor'] == cursor: raise IntegrationError('微信分页游标没有前进')
                            cursor = result['cursor']
                        else: more = True
                    except Exception as exc:
                        more = True
                        self.db.execute('UPDATE groups SET last_error=? WHERE id=?', (str(exc)[:800], group['id']))
                self.last_fingerprint, self.more_pending = fingerprint, more
            for group in groups:
                for msg in self.db.rows("SELECT * FROM messages WHERE group_id=? AND state='new' ORDER BY timestamp,created LIMIT 100", (group['id'],)):
                    self.process_message(msg, group)
            for event in self.db.rows("SELECT e.id,e.group_id FROM events e JOIN groups g ON g.id=e.group_id WHERE e.state='ready' AND g.enabled=1 LIMIT 40"):
                try: self.publish(event['id'], automatic=True)
                except Exception: pass  # Error and original payload are persisted by publish.
            self.runtime['last_check'] = time.time()
            return {'groups': len(groups), 'messages': total}
        except Exception as exc:
            self.runtime['error'] = str(exc)
            raise
        finally:
            self.runtime['state'] = 'idle'; self.sync_lock.release()

    def publish(self, event_id, edits=None, target_event_id=None, automatic=False):
        with self.publish_lock:
            row = self.db.one('SELECT * FROM events WHERE id=?', (event_id,))
            if not row: raise ValueError('找不到待处理日程')
            if row['state'] in ('synced', 'duplicate', 'updated'): return {'ok': True, 'already_synced': True}
            if row['state'] == 'ignored': raise ValueError('这条通知已忽略')
            event = json.loads(row['payload'])
            if edits and row['fingerprint']: raise ValueError('这条日程已有同步尝试，请使用原内容重试，成功后在飞书中修改')
            if edits: event = validate_event({**event, **edits})
            else: event = validate_event(event)
            if automatic:
                group = self.db.one('SELECT * FROM groups WHERE id=?', (row['group_id'],))
                if not group or not group['enabled'] or group['mode'] != 'auto': return {'paused': True}
                if row['state'] != 'ready' or json.loads(row['reasons']): return {'needs_review': True}
            try:
                identity = self.lark.identity()
                account = identity['profile'] + ':' + identity['account']
                if not identity['available']: raise IntegrationError('飞书用户身份不可用')
                if self.db.get('lark_account') != account: raise IntegrationError('飞书账号已变更，已停止写入')
                calendar_id = self.canonical_calendar(row['calendar_id'])
                fp = event_fingerprint(event)
                claim = self.db.one('SELECT * FROM claims WHERE calendar_id=? AND fingerprint=?', (calendar_id, fp))
                if claim and claim['event_id'] != event_id:
                    previous = self.db.one('SELECT * FROM events WHERE id=?', (claim['event_id'],))
                    if previous and previous['lark_id']:
                        self.db.execute("UPDATE events SET state='duplicate',lark_id=?,app_link=?,updated=? WHERE id=?", (previous['lark_id'], previous['app_link'], time.time(), event_id))
                        return {'duplicate': True, 'app_link': previous['app_link']}
                    raise IntegrationError('相同日程有一次未完成的同步，请先重试原记录')
                target_event_id = target_event_id or row.get('operation_target')
                target = None
                if target_event_id:
                    target = self.db.one("SELECT * FROM events WHERE id=? AND state='synced' AND lark_id!=''", (target_event_id,))
                    if not target or self.canonical_calendar(target['calendar_id']) != calendar_id: raise ValueError('请选择同一目标日历中已同步的日程')
                with self.db.connect() as db:
                    db.execute('INSERT OR IGNORE INTO claims VALUES(?,?,?)', (calendar_id, fp, event_id))
                    db.execute("UPDATE events SET state='syncing',payload=?,fingerprint=?,operation_target=?,updated=? WHERE id=?", (json.dumps(event, ensure_ascii=False), fp, target_event_id or '', time.time(), event_id))
                if target:
                    response = self.lark.update(calendar_id, target['lark_id'], event, self.db.get('reminder', 5))
                else:
                    response = self.lark.create(calendar_id, event, 'wechat-feishu-calendar:' + account + ':' + event_id, self.db.get('reminder', 5))
                remote = response.get('data', {}).get('event', {})
                if not remote.get('event_id'): raise IntegrationError('飞书未返回日程编号，已保留同一请求编号供重试')
                if row['calendar_id'] == 'primary' and remote.get('organizer_calendar_id'):
                    self.db.set('primary_calendar_id', remote['organizer_calendar_id'])
                    self.db.execute('INSERT OR IGNORE INTO claims VALUES(?,?,?)', (remote['organizer_calendar_id'], fp, event_id))
                self.db.execute("UPDATE events SET state='synced',lark_id=?,app_link=?,error='',updated=? WHERE id=?", (remote['event_id'], remote.get('app_link', ''), time.time(), event_id))
                if target:
                    self.db.execute("UPDATE events SET state='updated',updated=? WHERE id=?", (time.time(), target_event_id))
                return {'ok': True, 'event_id': remote['event_id'], 'app_link': remote.get('app_link', '')}
            except Exception as exc:
                self.db.execute("UPDATE events SET state='error',error=?,updated=? WHERE id=?", (str(exc)[:800], time.time(), event_id))
                raise

    def preview_group(self, group_id, days=3):
        group = self.db.one('SELECT * FROM groups WHERE id=?', (group_id,))
        if not group: raise ValueError('请先添加同步群')
        since = int(time.time()) - min(max(int(days), 1), 7) * 86400
        result = self.source.call('messages', group_id=group_id, cursor=[since, '', 0], limit=500)
        parsed = []
        for msg in result['messages']:
            if msg['type'] != 'text': continue
            found = extract(msg['text'], msg['timestamp'])
            if found['events'] or found['issues']:
                parsed.append({'message': msg, 'result': found})
        return {'notifications': parsed[-30:], 'read_count': len(result['messages']), 'has_more': result['has_more']}

    def stage_manual(self, data):
        calendar = self.calendar(data['calendar_id'])
        result = {'events': [validate_event(x) for x in data.get('events', [])[:30]], 'issues': []}
        message_id = data.get('message_id') or str(uuid.uuid4())
        group = {'id': data.get('group_id'), 'name': '手动导入', 'calendar_id': calendar['id'], 'calendar_name': calendar['name'], 'enabled': False}
        if group['id']:
            saved = self.db.one('SELECT * FROM groups WHERE id=?', (group['id'],))
            if not saved: raise ValueError('同步群不存在')
            group['name'] = saved['name']
        self.stage({'id': message_id, 'timestamp': received_time(data.get('received')).timestamp(), 'text': ''}, group, result, history=True)
        if data.get('message_id'): self.db.execute("UPDATE messages SET state='done' WHERE id=?", (message_id,))
        return {'count': len(result['events'])}

    def job(self, kind, fn):
        for job in self.jobs.values():
            if job['kind'] == kind and job['state'] == 'running': return job
        key = uuid.uuid4().hex
        self.jobs[key] = {'id': key, 'kind': kind, 'state': 'running', 'started': time.time()}
        def run():
            try: self.jobs[key].update(state='done', result=fn())
            except Exception as exc: self.jobs[key].update(state='error', error=str(exc))
        threading.Thread(target=run, daemon=True).start()
        while len(self.jobs) > 30:
            oldest = next((k for k,v in self.jobs.items() if v['state'] != 'running'), None)
            if oldest: del self.jobs[oldest]
            else: break
        return self.jobs[key]

    def start(self):
        def worker():
            while not self.stop.is_set():
                try: self.sync_once()
                except Exception: pass
                self.stop.wait(self.db.get('interval', 30))
        threading.Thread(target=worker, name='calendar-sync', daemon=True).start()
