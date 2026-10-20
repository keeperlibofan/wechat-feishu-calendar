"""Synthetic multi-day notices and automatic handling of optional details."""
import time

import pytest

from app.extractor import extract, received_time, validate_event
from app.service import App
from test_app import FakeLark, FakeSource


NOTICE = '''关于开展健康咨询服务的通知
为方便同学，现将活动安排通知如下。
一、时间：
10月20日至23日
上午：9:00—12: 00
下午：14:30—17:00
三、地点:
示例楼2楼会议室
欢迎有需求的同学自愿参加！'''


def test_multiday_notice_expands_every_daily_slot_and_reads_numbered_location():
    result = extract(NOTICE, '2026-10-20T08:00:00+08:00')
    events = result['events']
    assert not result['issues']
    assert len(events) == 8
    assert [(e['start'][8:10], e['start'][11:16], e['end'][11:16]) for e in events] == [
        (str(day), start, end) for day in range(20, 24)
        for start, end in [('09:00', '12:00'), ('14:30', '17:00')]]
    assert all(e['title'] == '关于开展健康咨询服务的通知' for e in events)
    assert all(e['location'] == '示例楼2楼会议室' and not e['reasons'] for e in events)


@pytest.mark.parametrize(('span', 'first', 'last', 'count'), [
    ('10月20日—10月23日', '2026-10-20', '2026-10-23', 4),
    ('10月20日（周二）至23日（周五）', '2026-10-20', '2026-10-23', 4),
    ('10月20-23日', '2026-10-20', '2026-10-23', 4),
    ('2026年10月30日至11月2日', '2026-10-30', '2026-11-02', 4),
    ('12月30日至1月2日', '2026-12-30', '2027-01-02', 4),
    ('2026年12月31日至2027年1月2日', '2026-12-31', '2027-01-02', 3),
    ('2026-10-30 至 2026-11-02', '2026-10-30', '2026-11-02', 4),
    ('10月20日至23日工作日', '2026-10-20', '2026-10-23', 4),
    ('10月23日至26日（工作日）', '2026-10-23', '2026-10-26', 2),
])
def test_date_span_formats_keep_inclusive_endpoints(span, first, last, count):
    text = f'学院培训通知\n{span}\n时间：09:00-11:00\n地点：会议室'
    events = extract(text, '2026-10-19T08:00:00+08:00')['events']
    assert len(events) == count
    assert events[0]['start'][:10] == first and events[-1]['start'][:10] == last
    assert all(not e['reasons'] for e in events)


def test_bounded_daily_notice_does_not_require_an_unbounded_recurrence_rule():
    events = extract(NOTICE.replace('上午：', '每天上午：'), '2026-10-19T08:00+08:00')['events']
    assert len(events) == 8 and all(not e['reasons'] for e in events)


def test_date_only_span_is_all_day_without_inventing_hours():
    events = extract('学院培训活动\n10月20日至23日\n地点：会议室', '2026-10-19T08:00+08:00')['events']
    assert len(events) == 4
    assert all(e['all_day'] and e['start'] == e['end'] and 'T' not in e['start'] for e in events)


@pytest.mark.parametrize('span', ['10月23日至20日', '10月32日至33日', '2026年10月20日至2028年10月23日',
                                  '10月20日（周三）至23日（周五）'])
def test_invalid_date_span_never_silently_becomes_first_day_only(span):
    result = extract(f'培训活动\n{span}\n时间：09:00-11:00', '2026-10-19T08:00+08:00')
    assert result['issues'] or all(e['reasons'] and not e['start'] for e in result['events'])


def test_empty_location_heading_does_not_consume_next_section():
    events = extract('明天\n培训活动\n时间：09:00-11:00\n三、地点：\n四、人员要求：\n全体同学',
                     '2026-10-19T08:00+08:00')['events']
    assert not events[0]['location']


@pytest.mark.parametrize(('interval', 'start', 'end'), [
    ('10月20日09:00至10月23日17:00', '2026-10-20T09:00', '2026-10-23T17:00'),
    ('2026-10-20 09:00—2026-10-23 17:00', '2026-10-20T09:00', '2026-10-23T17:00'),
    ('12月31日下午2:00至1月2日下午5:00', '2026-12-31T14:00', '2027-01-02T17:00'),
])
def test_explicit_continuous_interval_keeps_both_endpoint_dates(interval, start, end):
    event, = extract(f'学院培训活动\n时间：{interval}\n地点：会议室', '2026-10-19T08:00+08:00')['events']
    assert event['start'].startswith(start) and event['end'].startswith(end)
    assert not event['reasons']


def test_explicit_continuous_activity_longer_than_a_week_is_valid():
    event, = extract('学院培训活动\n时间：10月20日09:00至11月3日17:00\n地点：会议室',
                     '2026-10-19T08:00+08:00')['events']
    assert validate_event(event)['end'].startswith('2026-11-03T17:00')


def test_explicit_continuous_interval_keeps_other_daily_slots_in_same_block():
    events = extract('培训活动\n时间：10月20日09:00至10月21日17:00\n地点：会议室\n时间：18:00-19:00\n地点：教室',
                     '2026-10-19T08:00+08:00')['events']
    assert len(events) == 2 and [e['location'] for e in events] == ['会议室', '教室']


@pytest.mark.parametrize(('change', 'blocked'), [
    ('\n活动取消', True), ('\n三、地点：', False),
    ('\n人员：仅限未提供的身份', False), ('\n', False),
])
def test_only_material_uncertainty_blocks_automatic_sync(tmp_path, monkeypatch, change, blocked):
    monkeypatch.setattr(time, 'time', lambda: received_time('2026-10-19T08:00+08:00').timestamp())
    app = App(tmp_path, FakeSource(), FakeLark())
    app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    text = '培训活动\n10月20日\n时间：09:00-11:00' + change
    group = app.db.one('SELECT * FROM groups LIMIT 1')
    app.stage({'id': 'optional', 'text': text, 'timestamp': time.time()}, group, extract(text, time.time()))
    event, = app.db.events()
    assert event['state'] == ('pending' if blocked else 'ready')
    assert all('未识别到地点' not in reason for reason in event['reasons'])
    assert event['event']['notes']


def test_multiday_sync_writes_all_slots_once_when_relevance_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: received_time('2026-10-19T08:00+08:00').timestamp())
    class Source(FakeSource):
        def call(self, action, **params):
            if action == 'groups': return super().call(action, **params)
            return {'messages': [{'id': 'multi-day', 'type': 'text', 'text': NOTICE,
                                  'timestamp': int(time.time()), 'sender': '示例'}],
                    'cursor': [int(time.time()), 'db', 1], 'has_more': False}
    app = App(tmp_path, Source(), FakeLark())
    app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.db.set('profile', {'introduction': '我关注校内活动。'})
    app.db.set('model_enabled', True)
    monkeypatch.setattr('app.service.model_relevance', lambda *args: 'unknown')
    app.sync_once(force=True)
    app.sync_once(force=True)
    assert len(app.db.events()) == len(app.lark.calls) == 8
    assert all(e['state'] == 'synced' and not e['reasons'] for e in app.db.events())
    assert all('按不漏记原则收录' in e['event']['description'] for e in app.db.events())
    assert all('已通过个人信息相关性筛选' not in e['event']['description'] for e in app.db.events())
