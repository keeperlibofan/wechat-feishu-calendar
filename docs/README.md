# 文档与视觉素材

README 使用仓库内的 PNG 图片，避免依赖外部图床；图中的中文字体已经栅格化，在不同操作系统与 GitHub 主题下保持一致。

## 素材目录

| 图片 | 内容 |
| --- | --- |
| `assets/hero.png` | 品牌封面与微信通知到飞书日程的概念图 |
| `assets/notice-to-calendar.png` | 一条通知拆成两条日程的示例 |
| `assets/workflow.png` | 增量读取、校验、去重与处理分支 |
| `assets/architecture.png` | 本机数据处理、飞书与可选模型的数据流向 |
| `assets/overview.png` | 同步概览界面截图 |
| `assets/groups.png` | 群管理界面截图 |
| `assets/lab.png` | 实际识别器解析示例通知后的界面截图 |

## 重新生成图示

安装 `docs/requirements.txt` 中的 Pillow，并准备 `fontconfig` 与 Noto Sans CJK 字体（Ubuntu 包名为 `fontconfig`、`fonts-noto-cjk`），在仓库根目录运行：

```bash
python3 docs/tools/render_assets.py
```

插图坐标、配色和文案保存在 `tools/render_assets.py`，不会影响 App 运行。

## 重新拍摄界面

```bash
python3 docs/tools/demo.py
```

浏览器打开 <http://127.0.0.1:8767>。它复用实际 App 的网页与本地解析代码，但使用临时数据库和模拟连接，不启动同步线程，不读取真实微信数据库，不调用飞书或模型服务。退出进程后临时数据自动清理。

在同步概览、微信群管理和识别工作台分别拍摄完整页面，命名为 `readme-overview.png`、`readme-groups.png`、`readme-lab.png`，放入仓库外的同一目录。识别工作台使用以下虚构通知，消息日期设为 `2026-09-17 18:00`：

```text
同学们：
9月18日（周五）
智行科技校园招聘会
宣讲会时间：09:30-10:30
宣讲会地点：科教楼 A106
双选会时间：10:30-12:00
双选会地点：科教楼 A103
请携带简历，欢迎参加！
```

然后运行：

```bash
python3 docs/tools/render_assets.py --screenshots /path/to/screenshots
```

脚本为截图添加统一边框和“演示数据”标识。原始截图不应包含真实群名、账号、聊天内容或令牌。可以裁剪到页面的内容区域，保留完整功能内容；当前工作台截图已按此方式更新。
