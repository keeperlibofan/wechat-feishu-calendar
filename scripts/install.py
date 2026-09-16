#!/usr/bin/env python3
from pathlib import Path
import subprocess
import os

runtime=Path('/run/user')/str(os.getuid())
if (runtime/'bus').exists():
    os.environ.setdefault('XDG_RUNTIME_DIR',str(runtime))
    os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path='+str(runtime/'bus'))

root=Path(__file__).resolve().parents[1]
units=Path.home()/'.config/systemd/user'
apps=Path.home()/'.local/share/applications'
units.mkdir(parents=True,exist_ok=True);apps.mkdir(parents=True,exist_ok=True)
(units/'wechat-feishu-calendar.service').write_text(f'''[Unit]
Description=WeChat to Feishu Calendar
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart=/usr/bin/python3 -m app --port 8766
Environment=PATH={Path.home()}/.npm-global/bin:{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=TZ=Asia/Shanghai
UMask=0077
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
''')
(apps/'wechat-feishu-calendar.desktop').write_text(f'''[Desktop Entry]
Type=Application
Version=1.0
Name=群历 · 微信群日程助手
Comment=将指定微信群的通知同步到飞书日历
Exec=/usr/bin/python3 "{root}/scripts/launch.py"
Icon={root}/app/static/icon.svg
Terminal=false
Categories=Office;Calendar;
StartupNotify=true
''')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now','wechat-feishu-calendar.service'],check=True)
print('已安装应用菜单入口和登录后后台服务。访问 http://127.0.0.1:8766')
