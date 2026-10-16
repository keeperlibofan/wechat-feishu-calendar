"""Extensible local profile storage and conservative audience matching."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re


GENDER_WORDS = {
    'male': re.compile(r'男生|男性|男同学'),
    'female': re.compile(r'女生|女性|女同学'),
}


def _gender(value):
    value = str(value).strip().casefold()
    if value in ('男', '男性', '男生', 'male', 'm'): return 'male'
    if value in ('女', '女性', '女生', 'female', 'f'): return 'female'
    return ''


def _cohort(value):
    match = re.fullmatch(r'(?:20)?(\d{2})\s*级?', str(value).strip())
    return '20' + match.group(1) if match else ''


def normalize_profile(profile=None):
    """Read legacy fields without modifying storage; validate the extensible format."""
    profile = profile if isinstance(profile, dict) else {}
    raw = profile.get('attributes')
    if raw is None:
        raw = []
        gender, cohort = _gender(profile.get('gender', '')), _cohort(profile.get('cohort', ''))
        if gender: raw.append({'name': '性别', 'value': '男生' if gender == 'male' else '女生'})
        if cohort: raw.append({'name': '年级', 'value': cohort + '级'})
        tags = profile.get('tags', [])
        # Keep old free-form content, including punctuation, instead of reinterpreting it.
        if isinstance(tags, str): tags = [tags] if tags.strip() else []
        if isinstance(tags, list):
            raw.extend({'name': f'原关键词 {i + 1}', 'value': str(tag)} for i, tag in enumerate(tags) if str(tag).strip())
    if not isinstance(raw, list) or len(raw) > 200: raise ValueError('个人属性须为列表，最多保存 200 项')
    attributes, names = [], set()
    for item in raw:
        if not isinstance(item, dict): raise ValueError('个人属性格式无效')
        name, value = str(item.get('name', '')).strip(), str(item.get('value', '')).strip()
        kind, enabled = item.get('type', 'text'), item.get('enabled', True)
        if not name or len(name) > 80: raise ValueError('请填写属性名称，最多 80 个字符')
        if name.casefold() in names: raise ValueError('属性名称不能重复：' + name)
        if kind not in ('text', 'number', 'date'): raise ValueError('属性类型请选择文本、数字或日期')
        if not isinstance(enabled, bool): raise ValueError('请选择属性是否参与筛选')
        if len(value) > 2000: raise ValueError('单项属性值最多 2000 个字符')
        if value and kind == 'number':
            try:
                if not Decimal(value).is_finite(): raise InvalidOperation
            except InvalidOperation: raise ValueError('数字属性须填写有效数字：' + name) from None
        if value and kind == 'date':
            try:
                if date.fromisoformat(value).isoformat() != value: raise ValueError
            except ValueError: raise ValueError('日期属性须填写 YYYY-MM-DD 格式：' + name) from None
        attributes.append({'name': name, 'type': kind, 'value': value, 'enabled': enabled})
        names.add(name.casefold())
    introduction = str(profile.get('introduction', '')).strip()
    if len(introduction) > 10000: raise ValueError('个人介绍最多 10000 个字符')
    return {'attributes': attributes, 'introduction': introduction}


def filtering_profile(profile=None):
    """Only opted-in, nonempty attributes may participate or be sent to a model."""
    normalized = normalize_profile(profile)
    return {'attributes': [a for a in normalized['attributes'] if a['enabled'] and a['value']],
            'introduction': normalized['introduction']}


def _compare(value, condition, kind):
    condition = condition.strip()
    if not condition: return None
    if condition in ('不限', '全部', '所有', '任意'): return True
    if kind == 'text':
        if value.casefold() == condition.casefold(): return True
        return None if value.casefold() in condition.casefold() else False
    if kind == 'number':
        condition = re.sub(r'岁$', '', condition)
        span = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*(?:-|~|～|至|到)\s*(-?\d+(?:\.\d+)?)', condition)
        if span: return Decimal(span[1]) <= Decimal(value) <= Decimal(span[2])
        suffix = re.fullmatch(r'(-?\d+(?:\.\d+)?)(?:岁)?(以上|以下)', condition)
        if suffix: condition = ('>=' if suffix[2] == '以上' else '<=') + suffix[1]
    match = re.fullmatch(r'(>=|<=|>|<|≥|≤|至少|至多|不低于|不高于|超过|大于|小于|早于|晚于)?\s*(.+)', condition)
    operator, expected = match[1] or '=', match[2]
    try:
        left, right = (Decimal(value), Decimal(expected)) if kind == 'number' else (date.fromisoformat(value), date.fromisoformat(expected))
        if kind == 'number' and (not left.is_finite() or not right.is_finite()): return None
    except (InvalidOperation, ValueError): return None
    if operator in ('>=', '≥', '至少', '不低于'): return left >= right
    if operator in ('<=', '≤', '至多', '不高于'): return left <= right
    if operator in ('>', '超过', '大于', '晚于'): return left > right
    if operator in ('<', '小于', '早于'): return left < right
    return left == right


def _segment_result(segment, attributes):
    # Negation/grouping needs semantic interpretation; a keyword hit is insufficient.
    if re.search(r'非|除|不含|不包括|不是|不得|不属于|[（()）]', segment): return None
    if sum(bool(pattern.search(segment)) for pattern in GENDER_WORDS.values()) > 1: return None
    remaining, checks = segment, []
    for attr in sorted(attributes, key=lambda a: len(a['name']), reverse=True):
        separator = r'(?:[:：=]|为|是)' + ('?' if attr['type'] != 'text' else '')
        pattern = re.compile(re.escape(attr['name']) + r'\s*' + separator + r'\s*([^,，;；+＋/]+?)(?=[,，;；+＋/]|并且|且|$)')
        def explicit(match):
            condition = match[1].strip()
            if condition.casefold() != attr['value'].casefold():
                condition = re.sub(r'(?:的)?(?:全体)?(?:同学|人员|成员|学生)?$', '', condition).strip()
            result = _compare(attr['value'], condition, attr['type'])
            # Keep familiar aliases for migrated data and user-created equivalents.
            if attr['name'] in ('性别', 'gender') and _gender(condition): result = _gender(attr['value']) == _gender(condition) if _gender(attr['value']) else None
            if attr['name'] in ('年级', '入学年份', '入学年级', 'cohort') and _cohort(condition): result = _cohort(attr['value']) == _cohort(condition) if _cohort(attr['value']) else None
            checks.append(result)
            return ' '
        remaining = pattern.sub(explicit, remaining)
    cohorts = re.findall(r'(?<!\d)(20\d{2}|\d{2})\s*级', remaining)
    if cohorts:
        values = {_cohort(a['value']) for a in attributes if a['name'] in ('年级', '入学年份', '入学年级', 'cohort')} - {''}
        checks.append(_cohort(cohorts[0]) in values if values and len(cohorts) == 1 else None)
        remaining = re.sub(r'(?<!\d)(20\d{2}|\d{2})\s*级', ' ', remaining)
    for gender, pattern in GENDER_WORDS.items():
        if pattern.search(remaining):
            values = {_gender(a['value']) for a in attributes if a['name'] in ('性别', 'gender')} - {''}
            checks.append(gender in values if values else None)
            remaining = pattern.sub(' ', remaining)
    for attr in sorted(attributes, key=lambda a: len(a['value']), reverse=True):
        if attr['type'] != 'text': continue
        # A bare number/date can occur for unrelated reasons; require its property name.
        if not re.search(r'[^\d\W]', attr['value'], re.UNICODE): continue
        if attr['value'].casefold() in remaining.casefold():
            remaining = re.sub(re.escape(attr['value']), ' ', remaining, flags=re.I)
            checks.append(True)
    remaining = re.sub(r'全体|所有|同学们|同学|人员|成员|学生|参加者|均可|不限|仅限|面向|以及|并且|且|的|和|与|[\s,，;；:：=。]', '', remaining)
    if remaining: return None
    if any(c is False for c in checks): return False
    if any(c is None for c in checks): return None
    return True


def audience_decision(audience, profile=None):
    """Match completely understood alternatives; leave partial conditions for review."""
    audience = str(audience or '').strip()
    if not audience: return 'match'
    attributes = filtering_profile(profile)['attributes']
    segments = [x.strip() for x in re.split(r'[+＋、/]|或者|或', audience) if x.strip()]
    results = [_segment_result(segment, attributes) for segment in segments]
    if any(value is True for value in results): return 'match'
    if not results or any(value is None for value in results): return 'unknown'
    return 'exclude'
