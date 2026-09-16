"""Build the README illustrations; optionally frame browser screenshots.

Requires Pillow and Noto Sans CJK (see docs/README.md).
"""
import argparse
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parents[1] / 'assets'
OUT.mkdir(exist_ok=True)
S = 2
INK, MUTED, PURPLE, GREEN = '#212b49', '#68758d', '#6258dc', '#239d7a'
FONT = subprocess.check_output(['fc-match', '-f', '%{file}', 'Noto Sans CJK SC'], text=True)
BOLD = subprocess.check_output(['fc-match', '-f', '%{file}', 'Noto Sans CJK SC:style=Bold'], text=True)


class Canvas:
    def __init__(self, height, dark=False):
        self.w, self.h = 1600, height
        self.image = Image.new('RGB', (self.w*S, height*S))
        self.d = ImageDraw.Draw(self.image)
        a, b = ((17, 25, 48), (38, 40, 80)) if dark else ((249, 250, 255), (239, 241, 252))
        for y in range(height*S):
            t = y/(height*S)
            self.d.line((0, y, self.w*S, y), fill=tuple(round(v+(b[i]-v)*t) for i, v in enumerate(a)))

    def box(self, x, y, w, h, fill='white', outline=None, radius=22, width=1):
        self.d.rounded_rectangle(tuple(int(v*S) for v in (x, y, x+w, y+h)),
                                radius=int(radius*S), fill=fill, outline=outline, width=int(width*S))

    def text(self, x, y, content, size=26, color=INK, bold=False, anchor='lt'):
        font = ImageFont.truetype(BOLD if bold else FONT, int(size*S))
        self.d.text((int(x*S), int(y*S)), content, font=font, fill=color, anchor=anchor)

    def line(self, points, color='#c2c7e5', width=3):
        self.d.line([(int(x*S), int(y*S)) for x,y in points], fill=color, width=int(width*S), joint='curve')

    def dot(self, x, y, radius, fill):
        self.d.ellipse(tuple(int(v*S) for v in (x-radius,y-radius,x+radius,y+radius)),fill=fill)

    def arrow(self, a, b, color='#a0a4c5', width=3):
        self.line([a,b],color,width)
        angle=math.atan2(b[1]-a[1],b[0]-a[0])
        for delta in [-.55,.55]:
            self.line([b,(b[0]-14*math.cos(angle+delta),b[1]-14*math.sin(angle+delta))],color,width)

    def pill(self, x, y, w, label, fill='#eeedff', color=PURPLE, size=21):
        self.box(x,y,w,42,fill,radius=21)
        self.text(x+w/2,y+21,label,size,color,anchor='mm')

    def calendar(self, x, y, size=48, color=PURPLE):
        self.box(x,y+6,size,size-6,fill=None,outline=color,radius=8,width=3)
        self.line([(x,y+20),(x+size,y+20)],color,3)
        for p in [.28,.72]:self.line([(x+size*p,y),(x+size*p,y+12)],color,3)
        self.line([(x+size*.25,y+size*.64),(x+size*.43,y+size*.80),(x+size*.77,y+size*.45)],color,3)

    def chat(self,x,y,size=50,color=GREEN):
        self.box(x,y,size,size*.72,fill=None,outline=color,radius=12,width=3)
        self.line([(x+12,y+size*.72),(x+8,y+size*.95),(x+29,y+size*.72)],color,3)
        for p in [.27,.5,.73]:self.dot(x+size*p,y+size*.34,2,color)

    def heading(self, index, title, sub):
        self.text(64,44,index,17,PURPLE,True)
        self.text(64,90,title,43,INK,True)
        self.text(64,156,sub,23,MUTED)

    def save(self, name):
        self.image.resize((self.w,self.h),Image.Resampling.LANCZOS).save(OUT/(name+'.png'),optimize=True)


def hero():
    c=Canvas(650,True)
    glow=Image.new('RGBA',c.image.size)
    gd=ImageDraw.Draw(glow)
    gd.ellipse((820*S,-180*S,1650*S,640*S),fill=(114,85,236,45))
    c.image=Image.alpha_composite(c.image.convert('RGBA'),glow.filter(ImageFilter.GaussianBlur(70*S))).convert('RGB')
    c.d=ImageDraw.Draw(c.image)
    for x in range(760,1580,42):
        for y in range(45,630,42):c.dot(x,y,1,'#424164')
    c.box(76,54,60,60,'#7568ed',radius=17)
    c.calendar(89,67,34,'white')
    c.text(152,66,'群历',33,'#ffffff',True)
    c.text(239,78,'QUNLI',17,'#b8b5e3',True)
    c.text(80,165,'WECHAT  →  FEISHU CALENDAR',18,'#aea9e9',True)
    c.text(76,216,'把群通知，',76,'#ffffff',True)
    c.text(76,314,'安排进日历。',76,'#c3baff',True)
    c.text(81,433,'自动识别时间、地点与主题',26,'#c5ccde')
    c.text(81,478,'让重要安排，从聊天走进日历。',26,'#c5ccde')
    for x,w,label in [(80,150,'本机运行'),(246,150,'增量同步'),(412,150,'按群配置')]:
        c.pill(x,558,w,label,'#303854','#d6dded',20)
    c.box(846,76,656,194,'#29334e','#435170',24)
    c.chat(875,104,39,'#71d2ac')
    c.text(932,108,'来自选定微信群',24,'#cbd9e0',True)
    c.pill(1311,103,158,'示例通知','#35435b','#97dcbf',19)
    c.text(878,162,'智行科技校园招聘宣讲会',32,'#ffffff',True)
    c.text(878,220,'09 / 18    09:30–10:30   ·   科教楼 A106',23,'#c2cdde')
    c.arrow((1174,286),(1174,373),'#b4aaff',3)
    c.pill(1010,304,328,'提取  ·  校验  ·  去重','#7766e4','#ffffff',22)
    c.box(846,392,656,204,'#f8f8ff',None,24)
    c.box(873,423,80,84,'#ece9fc',radius=17)
    c.text(913,436,'SEP',17,PURPLE,True,anchor='mt')
    c.text(913,459,'18',36,PURPLE,True,anchor='mt')
    c.text(979,420,'校园招聘宣讲会',32,INK,True)
    c.text(979,473,'09:30–10:30  ·  求职日历',23,MUTED)
    c.line([(876,531),(1470,531)],'#e1e1ef',1)
    c.dot(888,562,5,GREEN)
    c.text(908,548,'清晰通知自动同步',22,GREEN,True)
    c.text(1470,548,'默认提前 5 分钟提醒',20,MUTED,anchor='rt')
    c.save('hero')


def example():
    c=Canvas(770)
    c.heading('01  /  FROM MESSAGE TO EVENTS','一条通知，拆成两个独立日程。','日期保持一致，时间与地点分别对应；一场宣讲，一场双选会。')
    c.box(64,224,658,470,'#ffffff','#dfe4ef',24)
    c.chat(95,256,42)
    c.text(155,262,'校园招聘通知',26,INK,True)
    c.pill(528,252,162,'消息示例','#e9f7f1',GREEN)
    c.line([(96,322),(690,322)],'#edf0f5',1)
    lines=['9月18日（周五）','智行科技校园招聘会','宣讲会时间：09:30–10:30','宣讲会地点：科教楼 A106','双选会时间：10:30–12:00','双选会地点：科教楼 A103']
    for i,line in enumerate(lines):c.text(100,355+i*47,line,25,INK,i==1)
    c.arrow((749,462),(828,462),PURPLE,4)
    for y,start,end,title,room,tint,accent in [(224,'09:30','10:30','智行科技校园招聘宣讲会','A106','#eceaff',PURPLE),(470,'10:30','12:00','智行科技校园双选会','A103','#e5f5ef',GREEN)]:
        c.box(856,y,680,224,'white','#dfe4ef',24)
        c.box(856,y,12,224,accent,radius=6)
        c.pill(890,y+27,126,'09 / 18',tint,accent,21)
        c.text(1502,y+37,start+'–'+end,24,accent,True,anchor='rt')
        c.text(891,y+98,title,28,INK,True)
        c.text(891,y+158,'科教楼 '+room+'    →    求职日历',24,MUTED)
    c.save('notice-to-calendar')


def workflow():
    c=Canvas(820)
    c.heading('02  /  THE SYNC PIPELINE','每条通知，都有清晰去向。','明确的新安排自动添加；需要判断的内容，留在你能看见的位置。')
    for x,num,title,sub in [(64,'01','选择群与目标日历','每个群，都有独立规则'),(568,'02','增量读取新消息','保存处理位置，重启后继续'),(1072,'03','提取、校验与去重','识别主题、日期、时间和地点')]:
        c.box(x,235,464,194,'white','#dfe3f1',22)
        c.pill(x+26,260,70,num,'#eeebfc',PURPLE,23)
        c.text(x+26,322,title,31,INK,True)
        c.text(x+26,378,sub,23,MUTED)
    c.arrow((535,332),(558,332),PURPLE,3)
    c.arrow((1039,332),(1063,332),PURPLE,3)
    c.line([(1304,429),(1304,485),(296,485)],'#b8bdd9',3)
    for x in [296,800,1304]:c.arrow((x,485),(x,548),'#b8bdd9',3)
    for x,title,rule,desc,bg,accent in [(64,'自动写入飞书','信息完整、没有歧义的新通知','按规则创建日程，并设置提醒','#eaf7f2',GREEN),(568,'进入待确认','缺失信息 / 改期 / 历史补录','补充字段，或更新已有日程','#fff7e5','#af7b20'),(1072,'跳过重复活动','消息或对应活动已经处理','复用本地索引，减少重复日程','#eeedfc',PURPLE)]:
        c.box(x,568,464,180,bg,radius=22)
        c.text(x+27,597,title,31,accent,True)
        c.text(x+27,651,rule,23,INK)
        c.text(x+27,694,desc,22,MUTED)
    c.save('workflow')


def architecture():
    c=Canvas(800)
    c.heading('03  /  DATA & CONNECTIONS','本机处理，连接你已有的工具。','飞书写入复用 lark-cli；模型辅助按需开启，结果先经过人工确认。')
    c.box(64,235,944,482,'#f5f6ff','#dce0f2',26)
    c.pill(90,257,196,'在你的电脑上','#e8e7fc',PURPLE,22)
    c.box(96,361,294,218,'white','#dfe4ed',20)
    c.chat(124,389,40)
    c.text(124,453,'微信本机数据库',28,INK,True)
    c.text(124,511,'只读取选定的群',23,MUTED)
    c.arrow((402,473),(466,473),PURPLE,3)
    c.box(488,319,482,309,'white','#d9ddf0',22)
    c.calendar(521,351,44)
    c.text(588,354,'群历 App',32,INK,True)
    for y,num,label in [(430,'01','读取桥 · 独立缓存'),(485,'02','本地规则 · 提取与校验'),(540,'03','SQLite · 进度与去重索引')]:
        c.text(520,y,num,20,PURPLE,True)
        c.text(568,y,label,23,INK)
    c.text(96,661,'现有工具管理登录凭据  ·  网页仅监听本机',23,MUTED)
    c.arrow((1008,380),(1147,380),PURPLE,3)
    c.text(1090,301,'日程与',19,PURPLE,anchor='mt')
    c.text(1090,331,'原通知备注',19,PURPLE,anchor='mt')
    c.box(1174,249,362,221,'#eeebff','#ded8f5',22)
    c.calendar(1204,279,42)
    c.text(1205,350,'飞书目标日历',29,INK,True)
    c.text(1205,407,'创建 / 修改 / 提醒',23,MUTED)
    for x in range(1010,1141,19):c.line([(x,588),(min(x+9,1141),588)],'#aa9ad1',3)
    c.arrow((1134,588),(1150,588),'#aa9ad1',3)
    c.box(1174,508,362,209,'white','#e0dcf1',22)
    c.pill(1204,531,166,'可选 · 默认关','#f3edfc','#8266b4',20)
    c.text(1205,593,'模型辅助识别',29,INK,True)
    c.text(1205,650,'仅发送待识别的单条通知',22,MUTED)
    c.save('architecture')


def frame_screenshot(source, name, label):
    shot=Image.open(source).convert('RGB')
    width=1472
    height=round(shot.height*width/shot.width)
    c=Canvas(height+174)
    c.box(62,48,1476,height+66,'white','#dadeee',18)
    for x,col in [(88,'#f0a5a4'),(114,'#f0d79b'),(140,'#a7d7ba')]:c.dot(x,78,6,col)
    c.text(800,78,'群历  /  '+label,19,MUTED,anchor='mm')
    c.pill(1310,59,193,'演示数据','#eeedfa',PURPLE,18)
    c.image.paste(shot.resize((width*S,height*S),Image.Resampling.LANCZOS),(64*S,112*S))
    c.text(800,height+143,'实际 App 界面 · 使用虚构群名与通知',19,MUTED,anchor='mm')
    c.save(name)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--screenshots',type=Path,help='Directory with readme-{overview,groups,lab}.png')
    args=parser.parse_args()
    hero(); example(); workflow(); architecture()
    if args.screenshots:
        for name,label in [('overview','同步概览'),('groups','微信群管理'),('lab','识别工作台')]:
            frame_screenshot(args.screenshots/f'readme-{name}.png',name,label)
    print('Generated assets:',', '.join(p.name for p in sorted(OUT.glob('*.png'))))
