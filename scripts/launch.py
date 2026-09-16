#!/usr/bin/env python3
import subprocess
import time
import urllib.request
import webbrowser
import shutil
import sys
import os
from pathlib import Path

URL='http://127.0.0.1:8766'
runtime=Path('/run/user')/str(os.getuid())
if (runtime/'bus').exists():
    os.environ.setdefault('XDG_RUNTIME_DIR',str(runtime))
    os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path='+str(runtime/'bus'))
subprocess.run(['systemctl','--user','start','wechat-feishu-calendar.service'],capture_output=True)
for attempt in range(30):
    try:
        urllib.request.urlopen(URL+'/api/health',timeout=1).close()
        break
    except Exception:
        if attempt==2:
            subprocess.Popen(['/usr/bin/python3','-m','app'],cwd=Path(__file__).resolve().parents[1],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        time.sleep(.3)
browser=shutil.which('google-chrome') or shutil.which('chromium')
if browser:subprocess.Popen([browser,'--app='+URL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
else:webbrowser.open(URL)
