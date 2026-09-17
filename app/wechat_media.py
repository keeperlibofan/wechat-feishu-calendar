"""Exact local attachment lookup and verified image decoding. Never reads process memory.

V2 format/key derivation references are recorded in docs/media.md. Key material
stays in this subprocess and is never returned to the web app or written to disk.
"""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import struct
import xml.etree.ElementTree as ET

MAX_IMAGE_BYTES = 20 * 1024 * 1024


class MediaError(ValueError):
    code = 'unsupported_media'


def xml_root(text):
    if not isinstance(text, str) or len(text) > 200000 or re.search(r'<!DOCTYPE|<!ENTITY', text, re.I):
        return None
    try: return ET.fromstring(text)
    except ET.ParseError: return None


def classify(body, kind):
    base = int(kind) & 0xffffffff
    if base == 1: return {'type': 'text', 'text': body}
    root = xml_root(body)
    if base == 3:
        img = root.find('.//img') if root is not None else None
        return {'type': 'image', 'text': '[图片通知]', 'md5': img.get('md5', '') if img is not None else ''}
    if base == 49 and root is not None and root.findtext('.//appmsg/type') == '5':
        title = root.findtext('.//appmsg/title') or ''
        description = root.findtext('.//appmsg/des') or ''
        url = root.findtext('.//appmsg/url') or ''
        return {'type': 'article', 'text': '\n'.join([title, description, url]).strip(),
                'title': title, 'description': description, 'url': url}
    return {'type': 'other', 'text': ''}


def image_extension(data):
    if data.startswith(b'\xff\xd8\xff'): return 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP': return 'webp'
    if data.startswith((b'II*\x00', b'MM\x00*')): return 'tiff'
    return ''


def image_keys(account_name, config_root=None):
    """Read only kvcomm file names; verify every derived candidate on the image."""
    account = re.sub(r'_[0-9a-fA-F]{4}$', '', account_name)
    root = Path(config_root or Path.home() / '.xwechat')
    seen = set()
    for pattern in ('net*/kvcomm/key_*', 'radium/*/kvcomm/key_*', 'radium/*/*/kvcomm/key_*'):
        for path in root.glob(pattern):
            match = re.match(r'key_(\d+)_', path.name)
            if not match: continue
            code = int(match[1])
            if not 0 < code <= 0xffffffff or code in seen: continue
            seen.add(code)
            yield hashlib.md5(f'{code}{account}'.encode()).hexdigest()[:16].encode('ascii'), code & 255
            if len(seen) >= 128: return


def decode_dat(data, expected_md5, keys=()):
    if not re.fullmatch(r'[a-fA-F0-9]{32}', expected_md5): raise ValueError('图片缺少可信校验值')
    if not 16 <= len(data) <= MAX_IMAGE_BYTES: raise ValueError('图片尚未下载完整或超过 20 MB')
    def verified(plain):
        return image_extension(plain) and hashlib.md5(plain).hexdigest() == expected_md5.lower()
    if verified(data): return data
    if data[:6] in (b'\x07\x08V2\x08\x07', b'\x07\x08V1\x08\x07'):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        aes_size, xor_size = struct.unpack_from('<II', data, 6)
        cipher_size = (aes_size // 16 + 1) * 16
        if aes_size <= 0 or 15 + cipher_size + xor_size > len(data): raise ValueError('图片加密数据尚未下载完整')
        if data[2:4] == b'V1':
            keys = [(b'cfcd208495d565ef', x) for x in range(256)]
        for key, xor in keys:
            try: head = unpad(AES.new(key, AES.MODE_ECB).decrypt(data[15:15+cipher_size]), 16)
            except ValueError: continue
            if len(head) != aes_size or not image_extension(head): continue
            tail_at = len(data) - xor_size
            plain = head + data[15+cipher_size:tail_at] + bytes(v ^ xor for v in data[tail_at:])
            if verified(plain): return plain
        raise ValueError('尚未匹配到本机图片密钥或完整原图，稍后自动重试')
    for magic in (b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n', b'GIF89a', b'GIF87a', b'RIFF'):
        xor = data[0] ^ magic[0]
        if bytes(v ^ xor for v in data[:len(magic)]) != magic: continue
        plain = bytes(v ^ xor for v in data)
        if verified(plain): return plain
    raise ValueError('图片校验失败或格式暂不支持，稍后自动重试')


def locate_image(index_path, account_root, group_id, md5):
    if not re.fullmatch(r'[a-fA-F0-9]{32}', md5): raise ValueError('微信图片消息没有原图标识')
    group_hash = hashlib.md5(group_id.encode()).hexdigest()
    with closing(sqlite3.connect(f'file:{index_path}?mode=ro', uri=True)) as db:
        rows = db.execute('''SELECT i.file_name,d1.username,d2.username FROM image_hardlink_info_v4 i
            JOIN dir2id d1 ON i.dir1=d1.rowid JOIN dir2id d2 ON i.dir2=d2.rowid
            WHERE i.md5=? AND d1.username=?''', (md5.lower(), group_hash)).fetchall()
    for name, directory, month in rows:
        if not re.fullmatch(r'[a-fA-F0-9]{32}(?:_[ht])?\.dat', name) or not re.fullmatch(r'\d{4}-\d{2}', month): continue
        path = Path(account_root) / 'msg' / 'attach' / directory / month / 'Img' / name
        base = (Path(account_root) / 'msg' / 'attach' / group_hash).resolve()
        if path.resolve().is_relative_to(base) and path.is_file(): return path
    raise ValueError('原图还未下载到本机，后台会自动重试')


def decode_message_image(app, group_id, md5, data_dir):
    index = app.cache.get('hardlink/hardlink.db')
    if not index: raise ValueError('微信图片索引暂不可读，稍后自动重试')
    account = Path(app.db_dir).parent
    source = locate_image(index, account, group_id, md5)
    if source.stat().st_size > MAX_IMAGE_BYTES: raise MediaError('图片超过 20 MB 自动识别上限')
    plain = decode_dat(source.read_bytes(), md5, image_keys(account.name))
    folder = Path(data_dir) / 'images'; folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest = folder / (md5.lower() + '.' + image_extension(plain))
    if not dest.exists() or hashlib.md5(dest.read_bytes()).hexdigest() != md5.lower():
        temporary = dest.with_suffix('.tmp')
        temporary.write_bytes(plain); os.chmod(temporary, 0o600); temporary.replace(dest)
    return {'path': str(dest), 'md5': md5.lower(), 'verified': True}
