"""Read shared recruitment pages without browser cookies, login or JavaScript."""
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ARTICLE_HOSTS = {'mp.weixin.qq.com', 'm.bysjy.com.cn', 's.bysjy.com.cn'}
IMAGE_HOSTS = {'mmbiz.qpic.cn', 'mmbiz.qlogo.cn'}


class ArticleError(ValueError):
    def __init__(self, message, retryable=True):
        super().__init__(message); self.retryable = retryable


def check_url(url, hosts):
    try:
        parsed = urlsplit(url)
        permitted = parsed.scheme == 'https' and parsed.hostname in hosts and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except ValueError: permitted = False
    if not permitted:
        raise ArticleError('暂不支持这个链接；目前支持公众号文章和云就业招聘详情页', False)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError: raise ArticleError('文章网站暂时无法连接，稍后自动重试') from None
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ArticleError('文章地址没有解析到公开网站', False)
    return parsed


def fetch(url, image=False):
    hosts = IMAGE_HOSTS if image else ARTICLE_HOSTS
    check_url(url, hosts)
    class Redirect(urllib.request.HTTPRedirectHandler):
        max_redirections = 4
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_url(newurl, hosts)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'})
    limit = 12 * 1024 * 1024 if image else 3 * 1024 * 1024
    try:
        with urllib.request.build_opener(Redirect()).open(request, timeout=20) as response:
            data = response.read(limit + 1)
            if len(data) > limit: raise ArticleError('文章或图片超过处理大小上限', False)
            return data
    except urllib.error.HTTPError as exc:
        retryable = exc.code in (408, 425, 429) or exc.code >= 500
        reason = '稍后自动重试' if retryable else '页面不可访问，请核对原文'
        raise ArticleError(f'文章网站返回 HTTP {exc.code}，{reason}', retryable) from None
    except (OSError, urllib.error.URLError): raise ArticleError('文章读取暂时失败，稍后自动重试') from None


class NoticeHTML(HTMLParser):
    def __init__(self, content_only=False):
        super().__init__(convert_charrefs=True)
        self.content_only = content_only
        self.stack, self.parts, self.images = [], [], []
        self.content_depth = self.title_depth = self.skip_depth = None
        self.title_parts, self.meta_title = [], ''
        self.found_content = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        void = tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'area', 'wbr')
        if not void: self.stack.append(tag)
        depth = len(self.stack)
        if tag in ('script', 'style', 'noscript', 'iframe') and self.skip_depth is None: self.skip_depth = depth
        if attrs.get('id') == 'js_content': self.content_depth = depth; self.found_content = True
        if attrs.get('id') == 'activity-name': self.title_depth = depth
        if tag == 'meta' and attrs.get('property') == 'og:title': self.meta_title = attrs.get('content', '')
        active = not self.content_only or self.content_depth is not None
        if active and not self.skip_depth:
            if tag in ('p', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'br', 'tr'): self.parts.append('\n')
            if tag == 'img':
                url = attrs.get('data-src') or attrs.get('src', '')
                if url: self.images.append(url)

    def handle_endtag(self, tag):
        if tag not in self.stack: return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.skip_depth is not None and depth <= self.skip_depth: self.skip_depth = None
        if self.title_depth is not None and depth <= self.title_depth: self.title_depth = None
        if self.content_depth is not None and depth <= self.content_depth: self.content_depth = None
        del self.stack[depth-1:]
        if tag in ('p', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'tr'): self.parts.append('\n')

    def handle_data(self, data):
        if self.skip_depth: return
        if self.title_depth: self.title_parts.append(data)
        if not self.content_only or self.content_depth is not None: self.parts.append(data)

    @property
    def text(self):
        return '\n'.join(x.strip() for x in ''.join(self.parts).splitlines() if x.strip())[:45000]

    @property
    def title(self):
        return (''.join(self.title_parts).strip() or self.meta_title).strip()[:180]


def strip_html(value):
    parser = NoticeHTML(); parser.feed(str(value or '')); return parser.text


def read_article(url, fallback_title=''):
    parsed = check_url(url, ARTICLE_HOSTS)
    if parsed.hostname in ('m.bysjy.com.cn', 's.bysjy.com.cn'):
        if not parsed.path.rstrip('/').endswith('/chance/preachmeetingdetails'):
            raise ArticleError('这个云就业链接不是宣讲会详情页', False)
        query = parse_qs(parsed.query)
        career_id, token = query.get('career_id', [''])[0], query.get('token', [''])[0]
        if not re.fullmatch(r'\d{1,15}', career_id) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', token):
            raise ArticleError('招聘分享链接缺少活动编号', False)
        endpoint = f'https://{parsed.hostname}/index.php?' + urlencode({'r': 'career/ajaxgetcareerdetail', 'token': token, 'career_id': career_id})
        raw = fetch(endpoint)
        try: response = json.loads(raw)
        except (ValueError, UnicodeError): raise ArticleError('招聘网站没有返回可识别的内容') from None
        if response.get('code') != 1 or not isinstance(response.get('data'), dict):
            raise ArticleError('招聘页面暂不可读取或需要登录', False)
        data = response['data']
        title = str(data.get('meet_name') or fallback_title)[:180]
        start = str(data.get('meet_time') or '')
        end = data.get('meet_end_time')
        location = str(data.get('address') or '')[:300]
        match = re.fullmatch(r'(20\d{2})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})', start)
        time_line = '时间：' + start
        if match and str(end).isdigit() and int(end) > 0:
            begin = datetime(*map(int, match.groups()), tzinfo=ZoneInfo('Asia/Shanghai'))
            finish = datetime.fromtimestamp(int(end), ZoneInfo('Asia/Shanghai'))
            if begin.date() == finish.date() and finish > begin:
                time_line = f'时间：{begin:%Y年%m月%d日 %H:%M}-{finish:%H:%M}'
        text = f'主题：{title}\n{time_line}\n地点：{location}'
        return {'text': text, 'description': strip_html(data.get('remark'))[:12000], 'images': [], 'title': title, 'url': url}
    html = fetch(url).decode('utf-8', errors='replace')
    parser = NoticeHTML(content_only=True); parser.feed(html)
    if not parser.found_content:
        raise ArticleError('公众号正文暂不可读取（可能需验证、登录或文章已删除）', False)
    title = parser.title or fallback_title
    urls = []
    for candidate in parser.images:
        candidate = urljoin(url, candidate)
        if urlsplit(candidate).hostname in IMAGE_HOSTS and candidate not in urls: urls.append(candidate)
    return {'text': '主题：' + title + '\n' + parser.text, 'images': urls[:6], 'title': title, 'url': url,
            'description': '', 'more_images': len(urls) > 6}


def article_image(url, data_dir):
    data = fetch(url, image=True)
    from .wechat_media import image_extension
    extension = image_extension(data)
    if not extension: raise ArticleError('文章内图片格式暂不支持', False)
    root = Path(data_dir) / 'images'; root.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = root / (hashlib.sha256(data).hexdigest() + '.' + extension)
    path.write_bytes(data); os.chmod(path, 0o600)
    return str(path)
