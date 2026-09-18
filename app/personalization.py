"""Match notification audience conditions against the user's local profile."""
from __future__ import annotations

import re


GENDER_WORDS = {
    'male': re.compile(r'男生|男性|男同学|男生同学'),
    'female': re.compile(r'女生|女性|女同学|女生同学'),
}


def normalize_profile(profile=None):
    profile = profile if isinstance(profile, dict) else {}
    gender = str(profile.get('gender', '')).strip().lower()
    if gender in ('男', '男性', '男生', 'male', 'm'):
        gender = 'male'
    elif gender in ('女', '女性', '女生', 'female', 'f'):
        gender = 'female'
    else:
        gender = ''
    cohort = str(profile.get('cohort', '')).strip()
    match = re.fullmatch(r'(?:20)?(\d{2})级?', cohort)
    if match:
        cohort = '20' + match.group(1)
    elif not re.fullmatch(r'20\d{2}', cohort):
        cohort = ''
    tags = profile.get('tags', [])
    if isinstance(tags, str):
        tags = re.split(r'[,，、;；\s]+', tags)
    tags = [str(tag).strip() for tag in tags if str(tag).strip()][:30]
    return {'gender': gender, 'cohort': cohort, 'tags': tags}


def _cohort_values(text):
    values = set()
    for value in re.findall(r'(?<!\d)(20\d{2}|\d{2})\s*级', text):
        values.add(value if len(value) == 4 else '20' + value)
    return values


def _segment_result(segment, profile):
    """Return true/false/None for a single alternative audience segment."""
    cohorts = _cohort_values(segment)
    gender = next((key for key, pattern in GENDER_WORDS.items() if pattern.search(segment)), '')
    recognized = bool(cohorts or gender)
    if cohorts:
        if not profile['cohort']:
            return None
        if profile['cohort'] not in cohorts:
            return False
    if gender:
        if not profile['gender']:
            return None
        if profile['gender'] != gender:
            return False
    if not recognized:
        for tag in profile['tags']:
            if tag and tag in segment:
                return True
        return None
    return True


def audience_decision(audience, profile=None):
    """Return ``match``, ``exclude`` or ``unknown`` for an audience condition.

    Alternatives joined by ``+`` or ``、`` are treated as separate eligible
    groups. A profile matches when at least one alternative matches.
    """
    audience = str(audience or '').strip()
    if not audience:
        return 'match'
    normalized = normalize_profile(profile)
    segments = [x.strip() for x in re.split(r'[+＋、,，/或]|\s+或\s+', audience) if x.strip()]
    results = [_segment_result(segment, normalized) for segment in segments]
    if any(value is True for value in results):
        return 'match'
    if any(value is None for value in results):
        return 'unknown'
    return 'exclude'


def profile_summary(profile=None):
    profile = normalize_profile(profile)
    parts = []
    if profile['gender']:
        parts.append('男生' if profile['gender'] == 'male' else '女生')
    if profile['cohort']:
        parts.append(profile['cohort'] + '级')
    parts.extend(profile['tags'])
    return '、'.join(parts)
