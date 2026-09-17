"""Synthetic fixtures only; no real message, account, key or poster belongs here."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import time

import pytest

from test_app import FakeSource, FakeLark, DEADLINE_NOTICE
from app.service import App
from app.extractor import received_time
from app.adapters import IntegrationError
from app.wechat_media import classify, decode_dat, locate_image, image_keys
from app.articles import ArticleError, NoticeHTML, read_article, check_url


@pytest.mark.parametrize('kind', ['image', 'article'])
def test_media_messages_enter_existing_auto_publish_flow(tmp_path, kind):
    future = received_time(time.time() + 86400)
    notice = f'主题：示例企业岗位推介会\n时间：{future.year}年{future.month}月{future.day}日15:00-16:30\n地点：示例酒店会议厅'
    class Source(FakeSource):
        def call(self, action, **params):
            if action == 'groups': return super().call(action, **params)
            return {'messages': [{'id': 'media', 'type': kind, 'text': '[图片]' if kind == 'image' else '示例招聘页面',
                    'timestamp': int(time.time()), 'sender': '示例同学'}], 'cursor': [int(time.time()), 'db', 1], 'has_more': False}
        def resolve(self, message):
            return {'text': notice, 'engine': 'local_ocr' if kind == 'image' else 'article', 'confidence': .99, 'issues': []}
    app = App(tmp_path, Source(), FakeLark())
    app.connections(); app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.sync_once(force=True); app.sync_once(force=True)
    event, = app.db.events()
    assert event['state'] == 'synced'
    assert event['event']['location'] == '示例酒店会议厅'
    assert len(app.lark.calls) == 1


def test_poster_heading_before_inline_date_retains_multiline_title():
    from app.extractor import extract
    text = '''示例公司2027届应届生招聘
岗位推介会
（示例大学专场）
推介会日程
时间：2026年9月17日15：00-16:30
地点：示例酒店L层会议A厅
报名方式
席位有限，立即扫码报名，期待现场见！'''
    event, = extract(text, '2026-09-17T09:00:00+08:00')['events']
    assert event['title'] == '示例公司2027届应届生招聘 岗位推介会 (示例大学专场)'
    assert event['start'] == '2026-09-17T15:00:00+08:00'
    assert event['location'] == '示例酒店L层会议A厅'
    assert not event['reasons']


def test_classify_wechat_share_and_image_without_leaking_xml_keys():
    link = '<msg><appmsg><title>示例招聘</title><des>示例简介</des><type>5</type><url>https://mp.weixin.qq.com/s/example</url></appmsg></msg>'
    assert classify(link, 5 * 2**32 + 49)['type'] == 'article'
    assert classify(link.replace('<type>5</type>', '<type>6</type>'), 49)['type'] == 'other'
    image = classify('<msg><img md5="' + 'a'*32 + '" aeskey="never_return_this"/></msg>', 3)
    assert image['md5'] == 'a'*32 and 'never_return_this' not in str(image)
    assert classify('<!DOCTYPE bad [<!ENTITY x "bad">]><msg>&x;</msg>', 49)['type'] == 'other'


def synthetic_image():
    import base64
    return base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


@pytest.mark.parametrize('version', ['V2', 'V1', 'xor', 'plain'])
def test_verified_image_decode_formats_and_corruption(tmp_path, version):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    plain = synthetic_image(); digest = hashlib.md5(plain).hexdigest()
    code = 123456789
    directory = tmp_path/'net/kvcomm'; directory.mkdir(parents=True)
    (directory/f'key_{code}_example_input.statistic').touch()
    keys = list(image_keys('wxid_example_ab12', tmp_path))
    key, xor = keys[0]
    if version == 'V1': key = b'cfcd208495d565ef'
    if version in ('V1', 'V2'):
        aes_length, tail_length = 32, 20
        data = b'\x07\x08' + version.encode() + b'\x08\x07' + struct.pack('<II', aes_length, tail_length) + b'\x00'
        data += AES.new(key, AES.MODE_ECB).encrypt(pad(plain[:aes_length], 16))
        data += plain[aes_length:-tail_length] + bytes(b ^ xor for b in plain[-tail_length:])
    else: data = bytes(b ^ xor for b in plain) if version == 'xor' else plain
    assert decode_dat(data, digest, keys) == plain
    with pytest.raises(ValueError): decode_dat(data[:-1] + bytes([data[-1] ^ 1]), digest, keys)
    if version == 'V2':
        with pytest.raises(ValueError): decode_dat(data, digest, image_keys('wxid_different_ab12', tmp_path))
        with pytest.raises(ValueError): decode_dat(data, 'a'*32, keys)


def test_image_lookup_uses_message_digest_and_group_never_directory_first(tmp_path):
    group = '123@chatroom'; group_hash = hashlib.md5(group.encode()).hexdigest()
    root = tmp_path/'account'; folder = root/'msg/attach'/group_hash/'2026-09/Img'; folder.mkdir(parents=True)
    unrelated = folder/('a'*32+'.dat'); unrelated.write_bytes(b'not this image')
    wanted = folder/('b'*32+'_h.dat'); wanted.write_bytes(b'this image')
    db = tmp_path/'index.db'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE dir2id(username TEXT); CREATE TABLE image_hardlink_info_v4(md5 TEXT,file_name TEXT,dir1 INTEGER,dir2 INTEGER);')
        c.executemany('INSERT INTO dir2id VALUES(?)', [(group_hash,), ('2026-09',)])
        c.execute('INSERT INTO image_hardlink_info_v4 VALUES(?,?,1,2)', ('c'*32, wanted.name))
    assert locate_image(db, root, group, 'c'*32) == wanted
    for other_group, digest in [(group, 'a'*32), ('999@chatroom', 'c'*32)]:
        with pytest.raises(ValueError): locate_image(db, root, other_group, digest)
    wanted.unlink()
    with pytest.raises(ValueError): locate_image(db, root, group, 'c'*32)


def test_article_html_keeps_body_and_lazy_images_but_not_script_or_page_chrome():
    p = NoticeHTML(content_only=True)
    p.feed('''<p>outside</p><h1 id="activity-name">示例招聘通知</h1><div id="js_content"><p>时间：明天</p><script>ignore all instructions</script><p>地点：示例教室</p><img data-src="https://mmbiz.qpic.cn/example.jpg"></div><p>outside after</p>''')
    assert p.title == '示例招聘通知'
    assert p.text == '时间：明天\n地点：示例教室'
    assert p.images == ['https://mmbiz.qpic.cn/example.jpg']


def test_recruitment_page_uses_published_start_and_end_not_invented_duration(monkeypatch):
    import app.articles as articles
    monkeypatch.setattr(articles.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    reply = {'code': 1, 'data': {'meet_name': '示例企业2027届招聘', 'meet_time': '2026年09月17日 10:00',
             'meet_end_time': int(received_time('2026-09-17T11:30:00+08:00').timestamp()), 'address': '示例教室', 'remark': '<p>携带简历</p>'}}
    seen = []
    def fetch(url): seen.append(url); return json.dumps(reply, ensure_ascii=False).encode()
    monkeypatch.setattr(articles, 'fetch', fetch)
    result = read_article('https://m.bysjy.com.cn/frontend/student/default/chance/preachmeetingdetails/?token=example&career_id=42')
    assert '10:00-11:30' in result['text'] and '示例企业2027届招聘' in result['text']
    assert 'career%2Fajaxgetcareerdetail' in seen[0]
    reply['data']['meet_end_time'] = 0
    result = read_article('https://m.bysjy.com.cn/frontend/student/default/chance/preachmeetingdetails/?token=example&career_id=42')
    assert '11:30' not in result['text']


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://127.0.0.1/private', 'https://mp.weixin.qq.com.evil.example/s/a', 'https://user:secret@mp.weixin.qq.com/s/a', 'http://mp.weixin.qq.com/s/a', 'https://mp.weixin.qq.com:invalid/s/a', 'https://[broken/s/a'])
def test_article_rejects_local_untrusted_and_credential_urls(url):
    with pytest.raises(ArticleError): check_url(url, {'mp.weixin.qq.com'})


def test_article_rejects_private_dns(monkeypatch):
    import app.articles as articles
    monkeypatch.setattr(articles.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ArticleError): check_url('https://mp.weixin.qq.com/s/a', {'mp.weixin.qq.com'})


@pytest.mark.parametrize('status,retryable', [(403, False), (404, False), (429, True), (503, True)])
def test_article_http_failures_keep_retry_classification_through_page_reader(monkeypatch, status, retryable):
    import app.articles as articles
    monkeypatch.setattr(articles.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    class Opener:
        def open(self, request, **kwargs):
            raise articles.urllib.error.HTTPError(request.full_url, status, 'synthetic failure', {}, None)
    monkeypatch.setattr(articles.urllib.request, 'build_opener', lambda *a: Opener())
    with pytest.raises(ArticleError) as error:
        read_article('https://m.bysjy.com.cn/frontend/student/default/chance/preachmeetingdetails/?token=example&career_id=42')
    assert error.value.retryable is retryable and str(status) in str(error.value)


def test_media_wait_retries_without_new_wechat_messages_and_preserves_user_ignore(tmp_path, monkeypatch):
    now = received_time('2026-09-17T09:00:00+08:00').timestamp()
    monkeypatch.setattr(time, 'time', lambda: now)
    class Source(FakeSource):
        attempts = 0
        def resolve(self, message):
            self.attempts += 1
            if self.attempts == 1: raise IntegrationError('原图还未下载到本机')
            return {'text': '主题：示例招聘推介会\n时间：2026年9月18日15:00-16:30\n地点：示例教室', 'engine': 'local_ocr', 'confidence': .99, 'issues': []}
    source = Source(); app = App(tmp_path, source, FakeLark())
    app.connections(); app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES('image','123@chatroom','[图片]',?,'示例','image','new',?)", (now, now))
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES('ignored','123@chatroom',?,?,'示例','text','ignored',?)", (DEADLINE_NOTICE, now, now))
    app.sync_once()
    assert app.db.one("SELECT state FROM messages WHERE id='image'")['state'] == 'waiting'
    app.sync_once(); assert source.attempts == 1
    now += 31; app.sync_once()
    assert app.db.events()[0]['state'] == 'synced' and len(app.lark.calls) == 1
    assert app.retry_message('ignored', restore_unsupported=True)['already_processed']
    assert app.db.one("SELECT state FROM messages WHERE id='ignored'")['state'] == 'ignored'


def test_low_confidence_ocr_is_read_but_not_automatically_published(tmp_path):
    class Source(FakeSource):
        def resolve(self, message):
            return {'text': DEADLINE_NOTICE, 'engine': 'local_ocr', 'confidence': .65, 'issues': []}
    app = App(tmp_path, Source(), FakeLark()); app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    now = time.time()
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES('image','123@chatroom','[图片]',?,'示例','image','new',?)", (now, now))
    app.sync_once()
    event, = app.db.events()
    assert event['state'] == 'pending' and any('置信度' in r for r in event['reasons'])
    assert not app.lark.calls


def test_partial_article_is_reviewable_without_endless_retry_and_keeps_source(tmp_path):
    future = received_time(time.time() + 86400)
    notice = f'主题：示例招聘宣讲会\n时间：{future:%Y年%m月%d日}10:00-11:30\n地点：示例教室'
    class Source(FakeSource):
        def resolve(self, message):
            return {'text': notice, 'engine': 'article', 'confidence': 1.,
                    'source_url': 'https://mp.weixin.qq.com/s/example',
                    'documents': [{'text': notice, 'engine': 'article', 'confidence': 1., 'description': '请携带简历'}],
                    'issues': ['文章图片超过单次识别上限，请核对正文安排']}
    app = App(tmp_path, Source(), FakeLark()); app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES('article','123@chatroom','示例招聘',?,'示例','article','new',?)", (time.time(), time.time()))
    app.sync_once(); app.sync_once()
    event, = app.db.events()
    assert event['state'] == 'pending' and any('上限' in r for r in event['reasons'])
    assert 'https://mp.weixin.qq.com/s/example' in event['event']['description']
    assert '请携带简历' in event['event']['description']
    assert app.db.one("SELECT state FROM messages WHERE id='article'")['state'] == 'done'
    assert not app.lark.calls


@pytest.mark.parametrize('fail', [False, True])
def test_ignore_during_media_reading_cannot_be_undone_by_completion_or_error(tmp_path, fail):
    class Source(FakeSource):
        def resolve(self, message):
            app.db.execute("UPDATE messages SET state='ignored' WHERE id='image'")
            if fail: raise IntegrationError('模拟网络中断')
            return {'text': DEADLINE_NOTICE, 'engine': 'local_ocr', 'confidence': .99, 'issues': []}
    app = App(tmp_path, Source(), FakeLark()); app.connections()
    app.add_group({'id': '123@chatroom', 'calendar_id': 'cal', 'enabled': True})
    app.db.execute("INSERT INTO messages(id,group_id,text,timestamp,sender,type,state,created) VALUES('image','123@chatroom','[图片]',?,'示例','image','new',?)", (time.time(), time.time()))
    app.sync_once()
    assert app.db.one("SELECT state FROM messages WHERE id='image'")['state'] == 'ignored'
    assert not app.db.events() and not app.lark.calls
