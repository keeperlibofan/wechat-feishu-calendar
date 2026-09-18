"""Regression tests for personal audience matching and point-time notices."""
import time

from app.extractor import extract
from app.personalization import audience_decision, normalize_profile
from app.service import App
from test_app import FakeLark, FakeSource


NOTICE = '''@所有人
明天下午教育安排

时间：14:40
地点：101-401
人员：34级全体+35级女生

时间：15:20
地点：101-402
人员：35级全体男生
'''


def test_point_time_notice_extracts_audience_and_inherited_date():
    result = extract(NOTICE, '2026-09-17T18:04:00+08:00')
    assert [event['audience'] for event in result['events']] == ['34级全体+35级女生', '35级全体男生']
    assert [event['title'] for event in result['events']] == ['教育安排', '教育安排']
    assert result['events'][0]['start'] == '2026-09-18T14:40:00+08:00'
    assert result['events'][0]['end'] == '2026-09-18T15:20:00+08:00'
    assert result['events'][1]['start'] == '2026-09-18T15:20:00+08:00'
    assert result['events'][1]['end'] == '2026-09-18T15:50:00+08:00'


def test_personal_profile_matches_only_the_synthetic_male_alternative():
    profile = {'gender': 'male', 'cohort': '2035'}
    assert normalize_profile(profile) == {'gender': 'male', 'cohort': '2035', 'tags': []}
    assert audience_decision('34级全体+35级女生', profile) == 'exclude'
    assert audience_decision('35级全体男生', profile) == 'match'
    assert audience_decision('35级全体', {}) == 'unknown'


def test_matching_profile_filters_other_group_and_auto_publishes_selected_event(tmp_path):
    class Source(FakeSource):
        def call(self, action, **params):
            if action == 'groups': return super().call(action, **params)
            return {'messages': [{'id': 'audience', 'type': 'text', 'text': NOTICE,
                                  'timestamp': int(time.time()), 'sender': '示例'}],
                    'cursor': [int(time.time()), 'db', 1], 'has_more': False}

    app = App(tmp_path, Source(), FakeLark())
    app.db.set('profile', {'gender': 'male', 'cohort': '2035'})
    app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.sync_once(force=True)
    events = app.db.events()
    assert len(events) == 1
    assert events[0]['event']['audience'] == '35级全体男生'
    assert events[0]['state'] == 'synced'
    assert len(app.lark.calls) == 1
    assert '匹配个人条件：男生、2035级' in events[0]['event']['description']


def test_profile_does_not_hide_missing_end_time_without_an_audience(tmp_path):
    class Source(FakeSource):
        def call(self, action, **params):
            if action == 'groups': return super().call(action, **params)
            return {'messages': [{'id': 'no-audience', 'type': 'text',
                                  'text': '明天\n教育安排\n时间：14:40\n地点：101-401',
                                  'timestamp': int(time.time()), 'sender': '示例'}],
                    'cursor': [int(time.time()), 'db', 1], 'has_more': False}

    app = App(tmp_path, Source(), FakeLark())
    app.db.set('profile', {'gender': 'male', 'cohort': '2035'})
    app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.sync_once(force=True)
    event, = app.db.events()
    assert event['state'] == 'pending'
    assert '未提供结束时间，按 30 分钟估算' in event['reasons']
    assert not app.lark.calls
