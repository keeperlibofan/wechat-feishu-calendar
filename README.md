<p align="center">
  <img src="docs/assets/hero.png" alt="群历：把微信群通知安排进飞书日历，本机运行、增量同步、按群配置" width="100%">
</p>

<h1 align="center">群历 · 微信群日程助手</h1>

<p align="center">
  从选定微信群的新消息中，提取时间、地点和主题，自动添加到你的飞书日历。<br>
  <b>适合班级通知、招聘宣讲、课题组会议与校园活动。</b>
</p>

<p align="center">
  <code>Linux</code> · <code>Python 3.12+</code> · <code>SQLite</code> · <code>原生 JavaScript</code><br>
  <b>30 秒</b> 默认检查间隔　／　<b>1 → N</b> 多活动拆分　／　<b>5 分钟</b> 默认提前提醒
</p>

<p align="center">
  <a href="#features">功能一览</a> ·
  <a href="#preview">界面预览</a> ·
  <a href="#workflow">同步流程</a> ·
  <a href="#quickstart">快速开始</a> ·
  <a href="#data">数据流向</a> ·
  <a href="docs/guide.md">完整使用指南</a>
</p>

---

<a id="features"></a>

## 功能一览

| | 能做什么 | 使用场景 |
| :---: | :--- | :--- |
| 👥 | **按群设置规则**：选择微信群、目标飞书日历与处理方式 | 招聘群进求职日历，课题组群进科研日历 |
| 🔄 | **增量读取**：保存消息处理位置，重启后继续 | 默认每 30 秒检查，只处理后续新消息 |
| 🗓️ | **一条通知，多条日程**：分别提取每个环节的时间与地点 | 同一条招聘通知中的宣讲会与双选会 |
| ✨ | **自动添加与提醒**：明确的新通知直接写入飞书 | 默认提前 5 分钟提醒，也可修改 |
| ✍️ | **核对与更新**：模糊信息、取消和改期进入待确认 | 补充信息，或更新由 App 管理的已有日程 |
| 🧩 | **去重与重试**：保留消息索引和创建请求编号 | 拦截重复活动，失败后沿用原请求重试 |
| 🔎 | **历史预览与手动补录**：先识别、再核对、再录入 | 预览近期群通知，或直接粘贴通知文字 |
| 🌙 | **后台运行**：应用菜单入口 + 用户级 systemd 服务 | 关闭网页后，已启用的群仍继续检查 |

### 一条消息，怎样变成日程？

![通知拆分示意：同一场校园招聘的宣讲会与双选会被分别添加到求职日历](docs/assets/notice-to-calendar.png)

> 图中为虚构通知。示例分别生成 **09:30–10:30 的宣讲会**和 **10:30–12:00 的双选会**，两条日程保留各自的教室。相对日期以消息发送时间计算。

<a id="preview"></a>

## 界面预览

**同步概览：群与日历如何对应、哪些内容已同步、哪些需要确认，一眼可见。**

[![群历同步概览，展示示例群映射、同步统计与连接状态](docs/assets/overview.png)](docs/assets/overview.png)

<table>
  <tr>
    <th width="50%">按群管理</th>
    <th width="50%">识别工作台</th>
  </tr>
  <tr>
    <td><a href="docs/assets/groups.png"><img src="docs/assets/groups.png" alt="微信群管理：每个群可独立设置目标日历、同步模式和开关" width="100%"></a></td>
    <td><a href="docs/assets/lab.png"><img src="docs/assets/lab.png" alt="识别工作台：粘贴示例通知后，实际识别器生成两条日程候选" width="100%"></a></td>
  </tr>
  <tr>
    <td align="center">一个群、一套规则，随时开启或暂停。</td>
    <td align="center">左侧粘贴通知，右侧核对识别结果。</td>
  </tr>
</table>

<sub>以上截取自实际 App 的独立演示环境，群名、账号与通知均为示例数据。点击图片可查看大图。</sub>

<a id="workflow"></a>

## 同步流程

![同步流程：选择群与日历，增量读取，解析和去重，然后自动写入、等待确认或跳过重复](docs/assets/workflow.png)

默认自动模式下，**明确的新通知自动添加**；缺失信息、日期与星期冲突、改期或历史补录先进入“待确认”。也可以给某个群设置“所有通知都先确认”。

- **进度可持续**：处理位置保存在本机，服务重启后继续读取。
- **操作可追溯**：“同步记录”保留来源群、目标日历与处理结果。
- **失败可重试**：创建失败后沿用同一个请求编号；更新失败后继续更新原日程。

<a id="quickstart"></a>

## 快速开始

先准备 **Python 3.12+**、已登录的本机微信、可读取消息的 **wechat-cli** 环境，以及已登录的官方 **lark-cli**。App 核心仅使用 Python 标准库。

```bash
git clone https://github.com/keeperlibofan/wechat-feishu-calendar.git
cd wechat-feishu-calendar

# 改成你已配置完成的 wechat-cli 源码目录
export WECHAT_CLI_DIR="$HOME/文档/wechat/wechat-cli"

python3 -m app
```

打开 **<http://127.0.0.1:8766>**，完成这三步：

| ① 检查连接 | ② 配置微信群 | ③ 开启同步 |
| :--- | :--- | :--- |
| 确认本机微信与飞书账号可用 | 搜索群名，选择目标日历和处理模式 | 明确的新通知自动写入，其他内容进入待确认 |

安装应用菜单与登录后的后台服务：

```bash
/usr/bin/python3 scripts/install.py
```

需要自定义微信工具路径、端口、数据目录或管理后台服务，请看 **[完整安装与使用指南](docs/guide.md)**。源码目录应长期保留，安装后的服务直接引用该目录。

### 飞书连接：复用现有登录

App 直接调用本机 `lark-cli`。已有权限会继续复用，按实际功能补充缺少的权限即可。

| 功能 | 对应权限 |
| :--- | :--- |
| 列出可选日历 | `calendar:calendar:read` |
| 创建日程 | `calendar:calendar.event:create` |
| 修改日程 | `calendar:calendar.event:update` |

已有主日历写入权限时，使用主日历无需重复授权。如需读取完整日历列表，在“选择更多日历”中补充授权，完成后点击“我已完成授权”。

<a id="data"></a>

## 数据流向

![数据流向图：微信本机数据库经过群历的读取桥、本地规则和索引处理，再经现有工具写入飞书；模型辅助默认关闭](docs/assets/architecture.png)

- **本机网页**：仅监听 `127.0.0.1`，默认配置与索引位于 `~/.local/share/wechat-feishu-calendar/app.db`。
- **微信读取**：只读取选定的群，使用独立解密缓存，不修改原始微信数据库。
- **飞书日程**：活动信息及原通知备注发送到你选定的日历，登录凭据由现有工具管理。
- **模型辅助**：默认关闭。启用后，仅将需要辅助识别的单条通知发送到设置中显示的模型服务；提取结果先进入人工确认。

## 常见问题

<details>
<summary><b>关闭网页以后，还会继续同步吗？</b></summary>

安装并启用后台服务后会继续。电脑需要保持运行，微信需要在本机接收新消息。暂停某个群只需关闭对应的同步开关。

</details>

<details>
<summary><b>为什么以前的通知没有自动添加？</b></summary>

添加群时从当前时间开始读取。历史通知可以用“预览历史”手动补录，每次预览最近 3 天的首批最多 500 条消息；保存候选后仍需确认。

</details>

<details>
<summary><b>图片、语音和文件能自动识别吗？</b></summary>

当前自动处理文字通知。图片通知进入待补充，可将图中文字复制到识别工作台；语音、视频、文件和链接正文暂不自动解析。

</details>

<details>
<summary><b>已经有的日程，会重复创建吗？</b></summary>

App 对已处理消息和已管理、已导入的活动做本地去重。飞书中其他手动创建、未导入的日程不在去重索引内。

</details>

<details>
<summary><b>取消通知、移除群规则会删除日程吗？</b></summary>

取消和变更进入待确认，不自动删除已有日程。移除群规则保留已创建的飞书日程。App 不添加其他参会人，也不预订会议室。

</details>

## 开发与验证

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

**当前验证记录：23 项 Python 测试通过**，JavaScript 语法与 Python 编译检查通过。测试使用模拟接口，不向微信发消息或向真实飞书写入测试日程。完整范围见 [VERIFICATION.md](VERIFICATION.md)。

| 模块 | 职责 |
| :--- | :--- |
| `app/service.py` | 增量扫描、候选处理、发布与去重 |
| `app/extractor.py` | 本地通知解析与日程校验 |
| `app/wechat_bridge.py` | 微信数据库读取桥 |
| `app/adapters.py` | 微信、飞书与可选模型接口 |
| `app/store.py` | SQLite 持久化 |
| `app/static/` | 六个页面的原生网页界面 |

---

<p align="center">
  <b>群里的安排，日历里见。</b><br>
  <sub>本仓库包含代码、文档与示例素材，不包含个人聊天数据库、登录凭据或授权二维码。</sub><br>
  <sub><a href="docs/guide.md">使用指南</a> · <a href="VERIFICATION.md">验证记录</a> · <a href="docs/README.md">文档素材维护</a></sub>
</p>
