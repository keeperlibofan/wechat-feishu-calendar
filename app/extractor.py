"""Local notification extraction. Missing information never becomes an automatic write."""
from __future__ import annotations
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
DATE = re.compile(r'(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]')
ISO_DATE = re.compile(r'\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b')
RANGE = re.compile(r'(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:[-—–~～]+|至|到)\s*(\d{1,2})\s*[:：]\s*(\d{2})')
POINT_LINE = re.compile(r'^(?:时间|开始时间|开始|集合时间|签到时间|安排时间)\s*[:：]?\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*$')
CHANGE = re.compile(r'取消|改期|改为|调整为|时间调整|地点调整|延期|更正|变更|另行通知')
HINT = re.compile(r'宣讲|招聘|推介|双选|会议|讲座|报告会|活动|通知|报名|答辩|面试|开会|集合|培训|考试|安排')
BOILER = re.compile(r'^(同学们|各位|大家好|请|欢迎|就业办|联系人|电话|国防科大就业|https?://|重要|明[日天].*预告|今[日天].*预告|宣讲会$)')
ACTION = r'填写|填报|提交|补充(?:完善)?|完善|核对|确认|报名|报送|缴纳|缴费|完成'
DEADLINE = re.compile(r'截止|截至|最晚|(?:需|须|务必|必须|请|要|应).{0,12}(?:' + ACTION + r')|(?:内|前)(?:完成|提交|填写|填报|报名|报送|缴费)')
TIME_POINT = re.compile(r'\d{1,2}[:：]\d{2}|[\d一二三四五六七八九十两]+\s*[点时]|上午|下午|晚上|中午|早上|傍晚')


def received_time(value=None):
    if value is None:
        return datetime.now(TZ)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, TZ)
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def day_for(line, received):
    match = DATE.search(line) or ISO_DATE.search(line)
    if match:
        year, month, day = match.groups()
        year = int(year or received.year)
        if not match.group(1) and received.month == 12 and int(month) == 1:
            year += 1
        if not match.group(1) and received.month == 1 and int(month) == 12:
            year -= 1
        return datetime(year, int(month), int(day), tzinfo=TZ).date()
    for word, offset in [('大后天', 3), ('后天', 2), ('明天', 1), ('明日', 1), ('今天', 0), ('今日', 0)]:
        if word in line:
            return (received + timedelta(days=offset)).date()
    m = re.search(r'(下周|本周|这周|周|星期)([一二三四五六日天])', line)
    if m:
        weekday = '一二三四五六日'.index(m[2].replace('天', '日'))
        delta = weekday - received.weekday()
        if m[1] == '下周': delta += 7
        elif m[1] in ('周', '星期') and delta < 0: delta += 7
        return (received + timedelta(days=delta)).date()
    return None


def tidy_title(line):
    line = re.sub(r'^[\s📢📣!！:：\d、.]+', '', line).strip()
    line = re.sub(r'^(?:大后天|后天|明天|明日|今天|今日)(?:上午|下午|晚上|晚间)?', '', line).strip()
    return line.rstrip(':：;；。')[:180]


def deadline_event(text, normalized, ref):
    """Only day-level action deadlines become all-day events, never vague meetings."""
    clauses = [s.strip() for s in re.split(r'[。！!？?；;\n❗]+', normalized) if s.strip()]
    dates, reasons = set(), []
    for clause in clauses:
        if not DEADLINE.search(clause): continue
        if re.search(r'无需|无须|不用|不必|不需要|已完成|已提交|已填写|已缴', clause): continue
        # Do not discard a specified clock time or choose a day from a date range.
        if TIME_POINT.search(clause) or re.search(r'\d{1,2}月\d{1,2}[日号]前', clause):
            return None
        try:
            day = day_for(clause, ref)
        except ValueError:
            return None
        if day:
            if len(DATE.findall(clause)) + len(ISO_DATE.findall(clause)) > 1: return None
            if len(re.findall(r'大后天|后天|明天|明日|今天|今日|(?:下周|本周|这周|周|星期)[一二三四五六日天]', clause)) > 1: return None
            dates.add(day)
            weekday = re.search(r'(?:周|星期)([一二三四五六日天])', clause)
            if (DATE.search(clause) or ISO_DATE.search(clause)) and weekday:
                if day.weekday() != '一二三四五六日'.index(weekday[1].replace('天', '日')):
                    reasons.append('通知中的日期与星期不一致')
    if len(dates) != 1: return None
    if CHANGE.search(normalized): reasons.append('这是一条取消或变更通知，请核对原日程')
    if re.search(r'每周|每月|每年|每天|每星期', normalized): reasons.append('包含重复安排，请核对重复规则')
    titles = []
    for clause in clauses:
        for part in re.split(r'[,，]', clause):
            if re.search(r'无需|无须|不用|不必|不需要|无法|不能|已完成|已提交|已填写|已缴', part): continue
            match = re.search(r'(?:' + ACTION + r')([^,，。；;！!？?❗#]+)', part)
            if not match: continue
            title = re.split(r'截止|截至|最晚|https?://', match[0], maxsplit=1)[0].strip(' :：')
            if DATE.search(title) or ISO_DATE.search(title) or TIME_POINT.search(title): continue
            # A bare "今天需完成" does not supply a task name.
            if len(match[1].strip()) >= 2 and len(title) <= 80 and title not in ('完成填写', '完成提交', '完成报名'):
                titles.append(title)
    if not titles: return None
    day = dates.pop().isoformat()
    return {'title': max(titles, key=len) + '（截止）', 'start': day, 'end': day,
            'all_day': True, 'kind': 'deadline', 'location': '', 'description': text[:12000],
            'confidence': .96 if not reasons else .5, 'reasons': reasons,
            'correction': bool(CHANGE.search(normalized))}


def extract(text: str, received=None):
    if not isinstance(text, str) or len(text) > 50000:
        raise ValueError('通知文本最多 50,000 字')
    ref = received_time(received)
    normalized = unicodedata.normalize('NFKC', text).replace('\r', '')
    lines = [x.strip() for x in normalized.splitlines() if x.strip()]
    if not lines:
        return {'events': [], 'issues': [], 'engine': 'local'}
    blocks, block = [], []
    for line in lines:
        if (DATE.search(line) or ISO_DATE.search(line)) and block:
            blocks.append(block); block = []
        block.append(line)
    if block: blocks.append(block)
    inherited = None
    for line in lines[:4]:
        try:
            inherited = day_for(line, ref) or inherited
        except ValueError:
            pass
    events, issues = [], []
    heading_title = ''
    correction = bool(CHANGE.search(normalized))
    for block in blocks:
        day, date_error = inherited, ''
        for line in block:
            try:
                found = day_for(line, ref)
                if found: day = found; inherited = found
                weekday = re.search(r'(?:周|星期)([一二三四五六日天])', line)
                if (DATE.search(line) or ISO_DATE.search(line)) and weekday and day:
                    if day.weekday() != '一二三四五六日'.index(weekday[1].replace('天', '日')):
                        date_error = '通知中的日期与星期不一致'
            except ValueError:
                date_error = '日期无效'; day = None
        ranges = [(i, m, 'range') for i, line in enumerate(block) for m in RANGE.finditer(line)]
        if ranges:
            time_entries = ranges
        else:
            points = []
            for i, line in enumerate(block):
                point = POINT_LINE.match(line)
                if point:
                    points.append((i, point, 'point'))
            time_entries = points
        labeled_title = next((re.split(r'[:：]', line, 1)[1].strip() for line in block
                              if re.match(r'^(单位|主办单位|主题|活动名称|会议名称|标题)\s*[:：]', line)), '')
        candidates = [tidy_title(line) for line in block
                      if not (DATE.search(line) or ISO_DATE.search(line) or RANGE.search(line)
                              or re.search(r'时间\s*[:：]|地点\s*[:：]', line) or BOILER.search(line))
                      and not re.search(r'^(?:日程|安排)$|报名方式|参会部门|席位有限|扫码报名|期待.*见', line)
                      and (HINT.search(line) or ('专场' in line and len(line) < 60))]
        if not time_entries:
            if labeled_title or candidates: heading_title = tidy_title(labeled_title) or ' '.join(candidates[:3])[:180]
            continue
        base_title = tidy_title(labeled_title) or heading_title or (candidates[0] if candidates else '')
        heading_title = ''
        for number, (index, match, time_kind) in enumerate(time_entries):
            reasons = []
            if not day: reasons.append('未识别到明确日期')
            if date_error: reasons.append(date_error)
            if correction: reasons.append('这是一条取消或变更通知，请核对原日程')
            if re.search(r'每周|每月|每年|每天|每星期', normalized):
                reasons.append('包含重复安排，请在飞书中核对重复规则')
            h1, m1 = int(match.group(1)), int(match.group(2))
            if time_kind == 'range':
                h2, m2 = int(match.group(3)), int(match.group(4))
            elif number + 1 < len(time_entries):
                next_match = time_entries[number + 1][1]
                h2, m2 = int(next_match.group(1)), int(next_match.group(2))
            else:
                h2, m2 = h1, m1 + 30
                if m2 >= 60:
                    h2, m2 = h2 + m2 // 60, m2 % 60
                reasons.append('未提供结束时间，按 30 分钟估算')
            if re.search(r'下午|晚上|晚间', block[index][:match.start()]):
                if h1 < 12: h1 += 12
                if h2 < 12: h2 += 12
            start = end = ''
            try:
                if day:
                    begin = datetime(day.year, day.month, day.day, h1, m1, tzinfo=TZ)
                    finish = datetime(day.year, day.month, day.day, h2, m2, tzinfo=TZ)
                    if finish <= begin:
                        if '次日' in block[index] or '翌日' in block[index]: finish += timedelta(days=1)
                        else: raise ValueError('结束时间不晚于开始时间')
                    start, end = begin.isoformat(), finish.isoformat()
            except ValueError:
                reasons.append('时间范围无效')
            role_match = re.search(r'(宣讲会|推介会|双选会|招聘会|面试|笔试|报告会|会议)时间', block[index])
            role = role_match[1] if role_match else ''
            title = base_title
            if title and role:
                stem = re.sub(r'(宣讲招聘会|招聘宣讲会|宣讲会|双选会|招聘会)$', '', title)
                if role == '宣讲会' and title.endswith('招聘会') and not title.endswith('宣讲招聘会'):
                    stem += '招聘'
                title = stem + role
            if not title:
                reasons.append('未识别到活动名称'); title = role or '待补充活动名称'
            elif labeled_title and not HINT.search(title):
                title += '招聘宣讲会' if '宣讲' in normalized else '活动'
            stop = time_entries[number + 1][0] if number + 1 < len(time_entries) else len(block)
            near = block[index:stop]
            locations = [re.split(r'[:：]', line, 1)[1].strip() for line in near
                         if re.match(r'^.*?地点\s*[:：]', line)]
            if not locations:
                locations = [re.split(r'[:：]', line, 1)[1].strip() for line in block
                             if re.match(r'^(地点|活动地点)\s*[:：]', line)]
            location = locations[0] if locations else ''
            if not location: reasons.append('未识别到地点')
            audience = ''
            for line in near:
                audience_match = re.match(r'^(?:人员|对象|参加人员|参会人员|参会对象|面向)\s*[:：]\s*(.+)$', line)
                if audience_match:
                    audience = audience_match.group(1).strip()[:200]
                    break
            events.append({'title': title, 'start': start, 'end': end, 'location': location,
                           'audience': audience, 'description': text[:12000], 'confidence': .97 if not reasons else .5,
                           'reasons': list(dict.fromkeys(reasons)), 'correction': correction})
    if not events:
        deadline = deadline_event(text, normalized, ref)
        if deadline: events.append(deadline)
    if not events and (HINT.search(normalized) or DEADLINE.search(normalized) or re.search(r'\d{1,2}[:：]\d{2}', normalized)):
        issues.append('发现可能的通知，但日期、时间段或活动名称不完整，请手动补充或使用模型识别')
    return {'events': events, 'issues': issues, 'engine': 'local'}


def validate_event(event):
    title = str(event.get('title', '')).strip()
    if not title or len(title) > 180: raise ValueError('请填写 1–180 字的日程名称')
    if not event.get('start') or not event.get('end'): raise ValueError('请填写开始和结束时间')
    if event.get('all_day') is True:
        if not all(isinstance(event[k], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', event[k]) for k in ('start', 'end')):
            raise ValueError('全天日程请填写 YYYY-MM-DD 日期')
        start, end = date.fromisoformat(event['start']), date.fromisoformat(event['end'])
        if end < start: raise ValueError('结束日期不能早于开始日期')
        if (end - start).days >= 7: raise ValueError('超过 7 天的活动请在飞书中处理')
        return {**event, 'title': title, 'start': start.isoformat(), 'end': end.isoformat(),
                'location': str(event.get('location', ''))[:300], 'description': str(event.get('description', ''))[:12000]}
    start, end = received_time(event['start']), received_time(event['end'])
    if end <= start: raise ValueError('结束时间必须晚于开始时间')
    if end - start > timedelta(days=7): raise ValueError('超过 7 天的活动请在飞书中处理')
    return {**event, 'title': title, 'start': start.isoformat(), 'end': end.isoformat(),
            'location': str(event.get('location', ''))[:300], 'description': str(event.get('description', ''))[:12000]}


def event_end_time(event):
    # Feishu's all-day end date is inclusive; it expires at next local midnight.
    end = received_time(event['end'])
    return end + timedelta(days=1) if event.get('all_day') is True else end
