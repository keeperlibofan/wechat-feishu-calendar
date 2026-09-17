#!/usr/bin/env python3
"""Install a private OCR runtime once; no administrator rights are needed."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
runtime = Path(os.environ.get('CALENDAR_APP_DATA', str(Path.home() / '.local/share/wechat-feishu-calendar'))) / 'ocr-venv'
subprocess.run([sys.executable, '-m', 'venv', str(runtime)], check=True)
subprocess.run([str(runtime / 'bin/python'), '-m', 'pip', 'install', '-r', str(root / 'requirements-media.txt')], check=True)
print('本机 OCR 已安装，后台下次检查消息时会自动使用。')
