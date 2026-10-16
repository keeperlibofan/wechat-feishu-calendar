"""Regression tests for personal audience matching and point-time notices."""
import time

import pytest

from app.extractor import extract
from app.personalization import audience_decision, normalize_profile, filtering_profile
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
    assert [a['value'] for a in normalize_profile(profile)['attributes']] == ['男生', '2035级']
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
    assert '已通过个人信息相关性筛选' in events[0]['event']['description']


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



def attribute(name, value, kind='text', enabled=True):
    return {'name': name, 'value': value, 'type': kind, 'enabled': enabled}


def test_legacy_profile_preserves_free_text_and_normalization_is_idempotent():
    old = {'gender': '男', 'cohort': '35级', 'tags': ['我叫示例用户，我属于三区队', '机器人实验室']}
    normalized = normalize_profile(old)
    assert [a['value'] for a in normalized['attributes']] == ['男生', '2035级', *old['tags']]
    assert normalize_profile(normalized) == normalized
    assert old['tags'][0] == '我叫示例用户，我属于三区队'


@pytest.mark.parametrize(('audience', 'expected'), [
    ('三区队全体', 'match'), ('区队：三区队', 'match'), ('区队=四区队', 'exclude'),
    ('年龄：20-25岁', 'match'), ('年龄>=26', 'exclude'), ('年龄至少20', 'match'),
    ('出生日期：2001-02-03', 'match'), ('出生日期：2002-02-03', 'exclude'),
    ('三区队博士研究生', 'unknown'), ('35级男生且博士研究生', 'unknown'),
    ('区队：三区队博士研究生', 'unknown'), ('性别：不限', 'match'),
    ('年龄：全体同学', 'unknown'), ('出生日期早于2002-01-01', 'match'),
    ('身份：大学生', 'match'), ('身份：大学生全体', 'match'),
    ('35级女生及其他自愿者', 'unknown'), ('非三区队全体', 'unknown'),
    ('年级：2035级，性别：男生', 'match'), ('年级：2035级，性别：女生', 'exclude'),
])
def test_arbitrary_text_number_and_date_conditions_require_complete_match(audience, expected):
    profile = {'attributes': [attribute('区队', '三区队'), attribute('年龄', '25', 'number'),
                             attribute('出生日期', '2001-02-03', 'date'), attribute('性别', '男生'),
                             attribute('年级', '2035级'), attribute('身份', '大学生')]}
    assert audience_decision(audience, profile) == expected


def test_disabled_and_empty_attributes_cannot_approve_a_notification():
    profile = {'attributes': [attribute('区队', '三区队', enabled=False), attribute('专业', '')]}
    assert filtering_profile(profile)['attributes'] == []
    assert audience_decision('三区队全体', profile) == 'unknown'
    assert audience_decision('区队：四区队', profile) == 'unknown'


@pytest.mark.parametrize('attributes', [
    [attribute('年龄', 'NaN', 'number')], [attribute('年龄', 'twenty', 'number')],
    [attribute('出生日期', '2025-02-29', 'date')], [attribute('', '有值')],
    [attribute('姓名', '甲'), attribute('姓名', '乙')], [attribute('值', 'a', enabled='false')],
])
def test_invalid_profile_does_not_silently_drop_data(attributes):
    with pytest.raises(ValueError): normalize_profile({'attributes': attributes})


def personal_app(tmp_path, profile, model=True):
    app = App(tmp_path, FakeSource(), FakeLark())
    app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.db.set('profile', profile)
    app.db.set('model_enabled', model)
    return app


def stage_notice(app, message_id, text='明天设备维护会议', audience='', reasons=None):
    future = time.time() + 86400
    from app.extractor import received_time
    start = received_time(future).replace(hour=15, minute=0, second=0, microsecond=0)
    event = {'title': '设备维护会议', 'start': start.isoformat(), 'end': start.replace(hour=16).isoformat(),
             'location': '会议室', 'description': text, 'audience': audience, 'reasons': reasons or []}
    group = app.db.one('SELECT * FROM groups LIMIT 1')
    app.stage({'id': message_id, 'timestamp': time.time(), 'text': text}, group, {'events': [event]})


def test_introduction_filters_each_event_after_attributes_and_does_not_leak(tmp_path, monkeypatch):
    profile = {'attributes': [attribute('区队', '三区队'), attribute('姓名', '本机私密姓名', enabled=False)],
               'introduction': '我负责设备管理。不参加校外招聘。'}
    app = personal_app(tmp_path, profile)
    calls = []
    answers = iter(['match', 'exclude', 'unknown'])
    def relevance(event, text, selected_profile, received):
        calls.append((event['title'], text, selected_profile))
        return next(answers)
    monkeypatch.setattr('app.service.model_relevance', relevance)
    stage_notice(app, 'related', audience='三区队全体')
    stage_notice(app, 'unrelated', text='明天校外招聘活动')
    stage_notice(app, 'unsure', text='明天自愿活动')
    events = {e['message_id']: e for e in app.db.events()}
    assert len(calls) == 3
    assert all(c[2]['introduction'] == profile['introduction'] for c in calls)
    assert all([a['name'] for a in c[2]['attributes']] == ['区队'] for c in calls)
    assert events['related']['state'] == 'ready'
    assert 'unrelated' not in events
    assert events['unsure']['state'] == 'pending'
    assert '相关性' in events['unsure']['reasons'][0]
    assert all(profile['introduction'] not in e['event']['description'] and '本机私密姓名' not in e['event']['description'] for e in events.values())


@pytest.mark.parametrize('model', [False, True])
def test_introduction_missing_model_or_failed_model_keeps_candidate(tmp_path, monkeypatch, model):
    app = personal_app(tmp_path, {'introduction': '我负责设备维护。'}, model=model)
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise RuntimeError('service unavailable')
    monkeypatch.setattr('app.service.model_relevance', unavailable)
    stage_notice(app, 'waiting')
    event, = app.db.events()
    assert event['state'] == 'pending'
    assert len(calls) == int(model)
    assert not app.lark.calls


def test_attribute_mismatch_precedes_introduction_and_unknown_can_use_semantics(tmp_path, monkeypatch):
    app = personal_app(tmp_path, {'attributes': [attribute('区队', '三区队')], 'introduction': '我负责设备。'})
    calls = []
    def relevance(*args):
        calls.append(args)
        return 'match'
    monkeypatch.setattr('app.service.model_relevance', relevance)
    stage_notice(app, 'excluded', audience='区队：四区队')
    stage_notice(app, 'general', audience='负责设备的值班同学')
    event, = app.db.events()
    assert event['message_id'] == 'general'
    assert event['state'] == 'ready'
    assert len(calls) == 1
