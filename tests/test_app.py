import json
from pathlib import Path
import sys
import time
import types
import sqlite3
import threading
import urllib.request
import urllib.error
import pytest
from app.extractor import extract, validate_event, received_time, event_end_time
from app.adapters import Lark
from app.service import App
from app.__main__ import serve

# Synthetic notice: preserves date, multi-stage and recruitment-year cases.
NOTICE = '''同学们：
明日重要招聘宣讲活动预告如下：
📢📢📢宣讲会
9月16日（周三）
时间：9:30-11:30
地点：示例校区103教学楼106教室
单位：示例机关及其直属机构2027年度公务员招录宣讲会
9月16日（周三）：
示例研究院人才宣讲招聘会
宣讲会时间：15:00--16:00
宣讲会地点：示例校区103教学楼104教室
双选会时间：16:00--17:30
双选会地点：示例校区103教学楼103教室
9月16日（周三）
时间：19:00-20:30
地点：示例校区103教学楼102教室
单位：示例科技股份有限公司
请参加的同学们携带好简历！
就业办:示例老师，电话:00000000。'''


def test_notice_splits_four_events_and_preserves_recruitment_year():
    result = extract(NOTICE, '2026-09-15T22:00:00+08:00')
    assert len(result['events']) == 4
    assert [e['location'] for e in result['events']] == ['示例校区103教学楼106教室', '示例校区103教学楼104教室', '示例校区103教学楼103教室', '示例校区103教学楼102教室']
    assert [e['start'][11:16] for e in result['events']] == ['09:30', '15:00', '16:00', '19:00']
    assert all(e['start'].startswith('2026-09-16') and not e['reasons'] for e in result['events'])
    assert '2027年度' in result['events'][0]['title']
    assert result['events'][2]['title'] == '示例研究院人才双选会'


def test_separate_stages_keep_separate_locations():
    text = '''9月14日（周一）：
示例科技集团招聘会
宣讲会时间：8:30--9:30
宣讲会地点：示例校区103教学楼106教室
招聘会时间：9:30--12:00
招聘会地点：示例校区体育馆'''
    events = extract(text, '2026-09-14T14:00+08:00')['events']
    assert len(events) == 2 and events[1]['location'] == '示例校区体育馆'


def test_relative_day_uses_message_timestamp_not_today():
    events = extract('明天\n学院讲座\n时间：14:00-16:00\n地点：教学楼', '2026-12-31T23:59+08:00')['events']
    assert events[0]['start'] == '2027-01-01T14:00:00+08:00'


@pytest.mark.parametrize('mutation', [lambda s:s.replace('周三','周四'), lambda s:s.replace('9:30-11:30','11:30-9:30'), lambda s:s.replace('9月16日','9月31日'), lambda s:s+'\n活动取消'])
def test_conflicts_and_cancellations_require_review(mutation):
    result = extract(mutation(NOTICE), '2026-09-15T12:00+08:00')
    assert result['events'][0]['reasons']


def test_missing_time_is_never_invented():
    result = extract('明天开会，地点在办公室，时间待定', '2026-09-15T12:00+08:00')
    assert not result['events'] and result['issues']


def test_no_end_is_not_an_all_day_event():
    result = extract('明天15:00开会，请准时参加', '2026-09-15T12:00+08:00')
    assert not result['events']


def test_recurring_notice_requires_confirmation():
    result = extract('每周三\n学院讲座\n时间：14:00-16:00\n地点：教学楼', '2026-09-15T12:00+08:00')
    assert any('重复' in r for r in result['events'][0]['reasons'])


DEADLINE_NOTICE = '''@所有人 重要通知，请查看后填写！今天需完成，否则影响登记。
请核对统计表信息，并补充完善校园卡账号和登记日期。
【在线文档】示例信息统计表
https://example.invalid/sheet'''


def test_day_deadline_preserves_source_and_uses_message_date():
    result = extract(DEADLINE_NOTICE, '2026-09-17T09:24:00+08:00')
    event, = result['events']
    assert event['all_day'] is True and event['kind'] == 'deadline'
    assert event['start'] == event['end'] == '2026-09-17'
    assert event['title'] == '补充完善校园卡账号和登记日期（截止）'
    assert event['description'] == DEADLINE_NOTICE
    assert not event['location'] and not event['reasons']
    assert event_end_time(event).isoformat() == '2026-09-18T00:00:00+08:00'


@pytest.mark.parametrize('text', [
    '明天15:00前提交申请材料。',
    '明天下午需完成材料申报。',
    '请于9月18日前提交材料。',
    '尽快完成信息填报。',
    '今天需完成。',
    '9月31日截止，请提交申请材料。',
    '请9月18日提交申请材料，9月19日完成审核。',
    '请今天提交申请材料，明天完成审核。',
    '今天无需完成。请核对统计表信息。',
])
def test_ambiguous_or_clock_deadlines_are_not_converted_to_all_day(text):
    assert not extract(text, '2026-09-17T09:00:00+08:00')['events']


def test_day_deadline_conflict_and_recurrence_stay_reviewable():
    for text in ['9月18日（周四）截止，请提交申请材料。',
                 '每周五需完成信息填报。',
                 '今天需完成信息填报。此通知取消。']:
        assert extract(text, '2026-09-17T09:00:00+08:00')['events'][0]['reasons']


def test_all_day_lark_payload_uses_inclusive_dates_and_does_not_block_the_day(tmp_path):
    event = extract(DEADLINE_NOTICE, '2026-09-17T09:24:00+08:00')['events'][0]
    payload = Lark(tmp_path).payload(event)
    assert payload['start_time'] == payload['end_time'] == {'date': '2026-09-17'}
    assert payload['free_busy_status'] == 'free'
    assert payload['need_notification'] is False
    assert payload['reminders'] == []
    for start, end in [('2026-09-18', '2026-09-17'), ('2026-09-17T00:00:00+08:00', '2026-09-18'), ('2026-09-17', '2026-09-24')]:
        with pytest.raises(ValueError): validate_event({**event, 'start': start, 'end': end})


class FakeSource:
    def call(self, action, **kwargs):
        if action == 'groups': return [{'id':'123@chatroom','name':'测试通知群','last_message_at':0}]
        return {'messages':[], 'cursor':kwargs['cursor'], 'has_more':False}
    def fingerprint(self): return 'fingerprint', '/fake/wechat/account'


class FakeLark:
    def __init__(self): self.calls=[]; self.account='account'; self.fail=False
    def identity(self): return {'profile':'profile','account':self.account,'available':True,'name':'测试用户','status':'ready'}
    def calendars(self): return [{'id':'cal','name':'目标日历','writable':True,'primary':True}]
    def canonical(self, x): return 'cal' if x=='primary' else x
    def create(self, calendar_id, event, key, reminder):
        self.calls.append((calendar_id,event,key))
        if self.fail: raise RuntimeError('network timeout')
        return {'ok':True,'data':{'event':{'event_id':'evt-'+key[-8:],'app_link':'https://applink.feishu.cn/example'}}}
    def update(self, calendar_id, event_id, event, reminder):
        self.calls.append(('update',calendar_id,event_id,event))
        if self.fail: raise RuntimeError('update timeout')
        return {'ok':True,'data':{'event':{'event_id':event_id,'app_link':'https://applink.feishu.cn/example'}}}


@pytest.fixture
def app(tmp_path):
    lark=FakeLark(); a=App(tmp_path, FakeSource(), lark)
    a.connections(); a.add_group({'id':'123@chatroom','calendar_id':'cal','enabled':True})
    return a


def stage(app, mid='message1', changes=None, history=False):
    future = received_time(time.time()+86400).replace(hour=15,minute=0,second=0,microsecond=0)
    event={'title':'公司招聘宣讲会','start':future.isoformat(),'end':future.replace(hour=16).isoformat(),'location':'106教室','description':'活动通知','reasons':[]}
    event.update(changes or {})
    group=app.db.one('SELECT * FROM groups LIMIT 1')
    app.stage({'id':mid,'timestamp':time.time(),'text':'活动通知'},group,{'events':[event]},history=history)
    return app.db.one('SELECT * FROM events WHERE message_id=?',(mid,))['id']


def test_duplicate_messages_only_write_once(app):
    first=stage(app); app.publish(first)
    second=stage(app,'message2'); result=app.publish(second)
    assert result['duplicate'] and len(app.lark.calls)==1


def test_primary_alias_and_real_calendar_id_share_deduplication(app):
    first=stage(app);app.publish(first)
    app.lark.canonical=lambda x:x
    app.db.set('primary_calendar_id','cal')
    app.db.execute("UPDATE groups SET calendar_id='primary'")
    second=stage(app,'message2')
    assert app.publish(second)['duplicate']
    assert len(app.lark.calls)==1


def test_primary_alias_still_allows_group_settings_after_calendar_list_permission(app):
    app.db.execute("UPDATE groups SET calendar_id='primary'")
    app.edit_group('123@chatroom', {'enabled': False})
    group = app.db.one('SELECT * FROM groups')
    assert group['calendar_id'] == 'cal' and not group['enabled']


def test_retry_missed_today_deadline_publishes_once_and_keeps_cursor(app, monkeypatch):
    now = received_time('2026-09-17T11:00:00+08:00').timestamp()
    monkeypatch.setattr(time, 'time', lambda: now)
    cursor = app.db.one('SELECT cursor FROM groups')['cursor']
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,error,created) VALUES(?,?,?,?,?,'text','review','旧版不支持',?)",
                   ('deadline', '123@chatroom', DEADLINE_NOTICE, now-3600, '示例同学', now))
    result = app.retry_message('deadline')
    assert result['state'] == 'done' and result['events'][0]['state'] == 'synced'
    assert len(app.lark.calls) == 1 and app.lark.calls[0][1]['all_day'] is True
    assert app.retry_message('deadline')['already_processed']
    assert len(app.lark.calls) == 1
    assert app.db.one('SELECT cursor FROM groups')['cursor'] == cursor


def test_ignored_notice_is_not_restored_by_retry(app):
    now = time.time()
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES(?,?,?,?,?,'text','ignored',?)",
                   ('ignored-day', '123@chatroom', DEADLINE_NOTICE, now, '示例同学', now))
    assert app.retry_message('ignored-day')['already_processed']
    assert app.db.one("SELECT state FROM messages WHERE id='ignored-day'")['state'] == 'ignored'
    assert not app.db.events() and not app.lark.calls


def test_incremental_day_deadline_is_synced_once_across_checks(app):
    class Source(FakeSource):
        def call(self, action, **kwargs):
            if action == 'groups': return super().call(action, **kwargs)
            return {'messages': [{'id': 'new-deadline', 'text': DEADLINE_NOTICE,
                    'timestamp': int(time.time()), 'sender': '示例同学', 'type': 'text'}],
                    'cursor': [int(time.time()), 'db', 1], 'has_more': False}
    app.source = Source()
    app.sync_once(force=True)
    app.sync_once(force=True)
    assert len(app.lark.calls) == 1
    event, = app.db.events()
    assert event['state'] == 'synced' and event['event']['all_day'] is True


def test_expired_deadline_is_not_automatically_published(app, monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: received_time('2026-09-18T01:00:00+08:00').timestamp())
    event = extract(DEADLINE_NOTICE, '2026-09-17T09:24:00+08:00')['events'][0]
    eid = stage(app, changes=event)
    assert app.publish(eid, automatic=True)['needs_review']
    assert not app.lark.calls


def test_restart_after_uncertain_remote_success_reuses_idempotency_key(app):
    first=stage(app); app.lark.fail=True
    with pytest.raises(RuntimeError): app.publish(first)
    key=app.lark.calls[0][2]
    other=App(app.data_dir,app.source,app.lark);app.lark.fail=False;other.publish(first)
    assert app.lark.calls[-1][2]==key
    assert other.db.one('SELECT state FROM events WHERE id=?',(first,))['state']=='synced'


def test_cannot_mutate_uncertain_request_payload(app):
    first=stage(app);app.lark.fail=True
    with pytest.raises(RuntimeError): app.publish(first)
    with pytest.raises(ValueError,match='原内容'): app.publish(first,edits={'title':'new'})


def test_paused_group_blocks_automatic_publish(app):
    first=stage(app);app.edit_group('123@chatroom',{'enabled':False})
    assert app.publish(first,automatic=True)['paused']
    assert not app.lark.calls


def test_history_never_publishes_automatically(app):
    first=stage(app,history=True)
    assert app.publish(first,automatic=True)['needs_review']
    assert not app.lark.calls


def test_account_switch_blocks_write(app):
    first=stage(app);app.lark.account='other'
    with pytest.raises(RuntimeError,match='账号'):app.publish(first)
    assert not app.lark.calls


def test_changed_location_requires_review(app):
    first=stage(app);app.publish(first)
    second=stage(app,'message2',{'location':'其他教室'})
    assert app.db.one('SELECT state FROM events WHERE id=?',(second,))['state']=='pending'


def test_update_existing_managed_event_without_creating_second_remote_event(app):
    first=stage(app);app.publish(first)
    second=stage(app,'message2',{'location':'其他教室'})
    app.publish(second,target_event_id=first)
    assert app.lark.calls[-1][0]=='update'
    assert app.db.one('SELECT state FROM events WHERE id=?',(first,))['state']=='updated'


def test_failed_update_retries_as_update_not_create(app):
    first=stage(app);app.publish(first)
    second=stage(app,'message2',{'location':'其他教室'})
    app.lark.fail=True
    with pytest.raises(RuntimeError):app.publish(second,target_event_id=first)
    app.lark.fail=False
    app.publish(second)
    assert app.lark.calls[-1][0]=='update'


def test_cursor_advances_only_after_durable_ingest(app):
    class Source(FakeSource):
        def call(self,action,**kwargs):
            if action=='groups':return super().call(action,**kwargs)
            return {'messages':[{'id':'m','text':'大家好','timestamp':int(time.time()),'sender':'某同学','type':'text'}], 'cursor':[99,'db',7], 'has_more':False}
    app.source=Source();app.sync_once(force=True)
    assert app.db.one('SELECT state FROM messages WHERE id=?',('m',))['state']=='ignored'
    assert json.loads(app.db.one('SELECT cursor FROM groups')['cursor'])==[99,'db',7]


def test_group_pagination_across_same_timestamp_and_shards(tmp_path,monkeypatch):
    # Inject a fixture-backed wechat-cli; the bridge must never skip equal-time messages.
    paths={}
    for shard in ['message/message_0.db','message/message_1.db']:
        path=tmp_path/Path(shard).name;paths[shard]=str(path)
        import hashlib
        table='Msg_'+hashlib.md5(b'123@chatroom').hexdigest()
        with sqlite3.connect(path) as c:
            c.execute(f'CREATE TABLE {table}(local_id,server_id,local_type,create_time,message_content,WCDB_CT_message_content)')
            for i in range(1,4):c.execute(f'INSERT INTO {table} VALUES(?,?,1,100,?,0)',(i,1000+i+(100 if "_1" in shard else 0),'wxid_sender:\n活动通知'))
    class Cache:
        def get(self,k):return paths.get(k)
    class Context:
        def __init__(self):self.cache=Cache();self.decrypted_dir='';self.msg_db_keys=list(paths)
    package=types.ModuleType('wechat_cli');package.__path__=[]
    core=types.ModuleType('wechat_cli.core');core.__path__=[]
    monkeypatch.setitem(sys.modules,'wechat_cli',package);monkeypatch.setitem(sys.modules,'wechat_cli.core',core)
    for name,attrs in {'db_cache':{'DBCache':type('DBCache',(),{})},'context':{'AppContext':Context},'contacts':{'get_contact_names':lambda *_:{},'get_contact_full':lambda *_:[]},'messages':{'decompress_content':lambda v,_:v,'_parse_message_content':lambda v,*_:v.split(':\n',1)}}.items():
        m=types.ModuleType('wechat_cli.core.'+name);m.__dict__.update(attrs);monkeypatch.setitem(sys.modules,m.__name__,m)
    monkeypatch.setenv('CALENDAR_APP_DATA',str(tmp_path))
    from app.wechat_bridge import main
    cursor=[99,'',0];seen=[]
    while True:
        r=main({'action':'messages','group_id':'123@chatroom','cursor':cursor,'limit':2})
        seen.extend(m['id'] for m in r['messages']);cursor=r['cursor']
        if not r['has_more']:break
    assert len(seen)==len(set(seen))==6


def test_http_rejects_cross_site_writes_and_rebinding(app):
    server=serve(app,0);port=server.server_address[1]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    root=f'http://127.0.0.1:{port}'
    try:
        token=json.load(urllib.request.urlopen(root+'/api/bootstrap'))['token']
        for headers in [{}, {'X-App-Token':token,'Origin':'https://unrelated.example'}, {'X-App-Token':token,'Host':'evil.example'}]:
            req=urllib.request.Request(root+'/api/settings',data=b'{}',headers=headers)
            with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            assert e.value.code==403
        req=urllib.request.Request(root+'/api/settings',data=b'{"interval":60}',headers={'X-App-Token':token})
        assert json.load(urllib.request.urlopen(req))['ok']
    finally:server.shutdown();server.server_close()


def test_http_settings_persists_personal_profile(app):
    server = serve(app, 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f'http://127.0.0.1:{port}'
    try:
        token = json.load(urllib.request.urlopen(root + '/api/bootstrap'))['token']
        body = json.dumps({'interval': 30, 'reminder': 5, 'model_enabled': False,
                           'profile': {'gender': 'male', 'cohort': '35级', 'tags': '示例关键词, 课题组'}}).encode()
        req = urllib.request.Request(root + '/api/settings', data=body,
                                     headers={'X-App-Token': token, 'Content-Type': 'application/json'})
        assert json.load(urllib.request.urlopen(req))['ok']
        assert app.db.get('profile') == {'gender': 'male', 'cohort': '2035', 'tags': ['示例关键词', '课题组']}
        assert app.state()['settings']['profile'] == {'gender': 'male', 'cohort': '2035', 'tags': ['示例关键词', '课题组']}
    finally:
        server.shutdown(); server.server_close()
