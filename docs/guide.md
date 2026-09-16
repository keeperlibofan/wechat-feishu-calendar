# 群历 · 安装与使用指南

一个在 Linux 本机运行的小 App：从选定微信群的新消息中识别活动通知，提取时间、地点和主题，自动添加到指定的飞书日历。

适合班级群、招聘通知群、会议通知群等场景。一条通知包含多场活动时，会拆分成多条日程；不确定的内容会保留供人工确认。

## 主要功能

- **按群同步**：搜索已加入的微信群，为每个群分别设置目标飞书日历、处理模式和同步开关。
- **增量读取**：默认每 30 秒检查一次新消息，保存处理进度，重启后继续。添加群时从当前时间开始，历史消息可单独预览补录。
- **通知识别**：识别文字中的日期、时间段、活动名称和地点，支持同一通知内多个日期、多个活动环节。“明天”等相对时间按消息发送日期计算。
- **自动写入飞书**：明确的新通知直接创建日程，默认提前 5 分钟提醒。可选择全部通知先经过人工确认。
- **核对与更新**：缺失信息、日期与星期冲突、取消或改期通知进入“待确认”，可编辑候选，或更新由 App 管理的已有日程。
- **去重与重试**：按消息编号和目标日历中的活动信息去重；创建失败后重试沿用同一个请求编号，降低重复创建风险。
- **历史预览与手动录入**：预览最近 3 天的群通知，或粘贴通知到识别工作台，核对后添加。
- **后台运行**：提供应用菜单入口和用户级 systemd 服务，关闭网页后仍可继续同步。
- **可选模型辅助**：可复用本机 Codex 的 Responses API 配置，辅助识别本地规则无法解析的通知；默认关闭，模型结果进入人工确认。

## 工作流程

```text
选定微信群的新消息
        ↓
增量读取 → 本地提取活动信息 → 去重与校验
                              ├─ 信息明确：自动添加到选定的飞书日历
                              └─ 信息不完整或有变更：进入“待确认”
```

界面包含同步概览、微信群管理、待确认、同步记录、识别工作台、连接与设置六个页面。

## 环境要求

- Linux 桌面环境；已在 Ubuntu 上验证。
- Python 3.12 或更新版本。App 核心仅使用 Python 标准库，前端使用原生 JavaScript/CSS。
- 微信已在本机登录，能够接收并保存新消息。
- 已配置可正常读取本机微信数据库的 `wechat-cli` 源码目录及其 `.venv`。本项目通过该工具的 `wechat_cli.core` 模块读取消息，不负责初始化数据库密钥。
- 官方 `lark-cli` 已安装，并已完成飞书用户登录。App 复用现有身份和授权，不复制登录令牌。
- 安装后台服务需要用户级 systemd；只运行网页服务可直接启动 Python 模块。

## 快速启动

```bash
git clone https://github.com/keeperlibofan/wechat-feishu-calendar.git
cd wechat-feishu-calendar

# 改为本机已配置完成的 wechat-cli 源码目录
export WECHAT_CLI_DIR="/path/to/wechat-cli"

python3 -m app
```

打开 <http://127.0.0.1:8766>。默认的微信工具目录为 `~/文档/wechat/wechat-cli`，如位置不同，使用上面的环境变量指定。该目录中需要存在 `.venv/bin/python`。

也可指定监听端口和数据目录：

```bash
python3 -m app --port 8766 --data-dir "$HOME/.local/share/wechat-feishu-calendar"
```

## 使用方法

1. 在“连接与设置”检查微信与飞书状态。App 会复用本机 `lark-cli` 的已有登录与权限。
2. 如需列出全部可选日历，点击“选择更多日历”，补充日历列表读取权限。完成飞书授权后，回到 App 点击“我已完成授权”。已有主日历写入权限时，使用主日历无需重复授权。
3. 在“微信群管理”搜索群名，选择目标日历和处理模式，开启同步开关。
4. 在“同步记录”查看处理结果，在“待确认”中补充信息或处理变更。
5. 补录历史通知时使用“预览历史”；粘贴通知时使用“识别工作台”。两种方式均先核对再写入飞书。

飞书权限按操作分别检查：读取日历列表需要 `calendar:calendar:read`，创建和修改日程分别使用 `calendar:calendar.event:create`、`calendar:calendar.event:update`。

## 安装应用菜单与后台服务

在准备长期保留的源码目录中运行：

```bash
/usr/bin/python3 scripts/install.py
```

安装后可从应用菜单搜索“群历”，也可继续使用浏览器访问本机地址。安装脚本会启动 `wechat-feishu-calendar.service`，并设置用户登录后运行。

如果微信工具不在默认目录，为后台服务设置路径：

```bash
systemctl --user edit wechat-feishu-calendar.service
```

在编辑器中添加：

```ini
[Service]
Environment="WECHAT_CLI_DIR=/path/to/wechat-cli"
```

保存后执行 `systemctl --user restart wechat-feishu-calendar.service`。

常用管理命令：

```bash
systemctl --user status wechat-feishu-calendar.service
systemctl --user stop wechat-feishu-calendar.service
systemctl --user start wechat-feishu-calendar.service
```

安装后请保留源码目录，应用菜单和服务直接引用该位置。暂停单个群只需关闭该群的同步开关。

## 数据与识别范围

- 服务仅监听 `127.0.0.1`；群配置、消息处理进度和同步记录默认保存在 `~/.local/share/wechat-feishu-calendar/app.db`。
- 微信解密缓存使用独立目录，不修改原始微信数据库；只读取选定的群，不发送微信消息。
- 当前自动处理文字通知。图片通知进入待补充，可将文字复制到工作台；语音、视频、文件和链接正文暂不自动解析。
- 模型辅助默认关闭。启用后，仅将所选群中需要辅助识别的单条通知发送到设置中显示的模型服务。
- 只读取本机已有消息，电脑需保持运行，微信需继续接收消息。
- 历史预览每次最多读取最近 3 天的首批 500 条消息。历史候选需要人工确认，不会直接自动发布。
- 去重覆盖 App 已管理或导入的日程；飞书中其他手动创建的日程不在本地去重索引内。
- 不自动删除取消的日程，不添加其他参会人，不预订会议室。移除群规则保留已经创建的飞书日程。
- 仓库只包含代码、文档和测试；本机聊天数据库、缓存、凭据和授权二维码不随源码提交。

## 开发与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

测试使用模拟的微信和飞书接口，不会向微信发送消息或向真实飞书创建日程。Node.js 仅用于 JavaScript 语法检查，运行 App 不需要 Node.js。

代码结构：

```text
app/
  __main__.py       本机 HTTP 服务
  service.py        增量扫描、通知处理、发布与去重
  extractor.py      本地通知解析与日程校验
  wechat_bridge.py  微信数据库读取桥
  adapters.py       微信、飞书与可选模型接口
  store.py          SQLite 持久化
  static/          网页界面
scripts/           安装与启动脚本
tests/             自动测试
```

验证范围见 [VERIFICATION.md](../VERIFICATION.md)。
