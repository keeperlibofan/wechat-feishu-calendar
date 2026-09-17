"""Run bundled local OCR in its own Python environment, with no network calls."""
import json
import os
from pathlib import Path
import sys


def read_image(path):
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    Image.MAX_IMAGE_PIXELS = 25000000
    try:
        with Image.open(path) as im:
            if im.width * im.height > 25000000: raise ValueError('图片分辨率超过处理上限')
            im.load()
            image = im.convert('RGB')
    except (Image.DecompressionBombError, OSError):
        raise ValueError('图片无法完整打开或分辨率超过处理上限') from None
    import numpy as np
    rows, _ = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)(np.array(image))
    lines = [{'text': str(text).strip(), 'score': round(float(score), 5),
              'x': min(p[0] for p in box), 'y': min(p[1] for p in box)} for box, text, score in rows or []]
    lines.sort(key=lambda r: (round(r['y'] / 8), r['x']))
    lines = [r for r in lines if r['text']][:1000]
    return {'text': '\n'.join(r['text'] for r in lines)[:50000], 'lines': lines,
            'confidence': min((r['score'] for r in lines if len(r['text']) > 2), default=0),
            'engine': 'local_ocr', 'width': image.width, 'height': image.height}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        data = json.load(sys.stdin)
        root = (Path(os.environ['CALENDAR_APP_DATA']) / 'images').resolve()
        path = Path(data['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise ValueError('图片路径不在本机应用缓存内')
        print(json.dumps({'ok': True, 'data': read_image(path)}, ensure_ascii=False))
    except Exception as exc:
        if isinstance(exc, ImportError):
            code, error = 'media_setup', '本机 OCR 依赖不完整，请运行 scripts/install_ocr.py'
        elif isinstance(exc, ValueError):
            code, error = 'unsupported_media', str(exc)
        else:
            code, error = 'media_wait', str(exc)
        print(json.dumps({'ok': False, 'error': error, 'code': code}, ensure_ascii=False)); sys.exit(1)
