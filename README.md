# ASW-CR · 长荣货物 ETD 追踪系统

面向海运代理的船期查询工具：从 WPS 共享表格读取单号，查询长荣官网装货港最新 ETD，发现变化后写回共享表格，并保存查询结果、变更明细和任务历史。

日常使用只需点击 **手动同步数据**。支持 Windows 本地开发和 Ubuntu 云服务器运行。

macOS / Linux 本地开发见 [跨平台启动说明](docs/DEVELOPMENT.md#macos--linux)。

## 文档入口

| 你要做什么 | 阅读文档 |
|---|---|
| 在另一台电脑继续开发 | [换电脑开发指南](docs/DEVELOPMENT.md) |
| 了解代码职责与重构后的维护方式 | [代码结构与维护约定](docs/ARCHITECTURE.md) |
| 了解当前进度与业务约定 | [开发交接说明](docs/HANDOFF.md) |
| 配置 WPS、排查日期与同步问题 | [WPS 与业务规则](docs/WPS.md) |
| 安装、维护云端服务及备份 | [Ubuntu 原生部署](deploy/README.md) |
| 了解备用 Docker 方案 | [Docker 部署参考](deploy/DOCKER.md) |
| 保持现有产品与设计约定 | [PRODUCT.md](PRODUCT.md)、[DESIGN.md](DESIGN.md) |

## 已实现

- WPS 普通共享电子表格读取、按单号定位行、校验原始值后写回。
- 长荣 Booking / Bill of Lading 查询，按装货港与 Estimated Departure Date 表头提取日期。
- 同步任务内复用一个浏览器，默认两票并发；全局控制启动间隔，WPS 写入串行。
- 订单总览、搜索、已更新/异常筛选、同步进度及耗时。
- 历史变更、任务明细、运行记录和使用说明页面。
- SQLite 持久保存记录，服务重启后识别中断任务。
- Ubuntu systemd 后台运行，SSH 隧道跨电脑访问。

当前没有定时同步、自动运价判断、域名、HTTPS 网站入口或独立网页登录。已连接的访问者共享数据和同步权限。

## 新电脑快速启动（Windows）

先安装 Git、Python 3.12；Node.js 用于 JavaScript 测试，不是运行网页的必需项。

打开 PowerShell，在你想保存项目的目录执行：

```powershell
git clone https://github.com/Au-Lei/ASW-CR.git
cd ASW-CR
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

不需要激活虚拟环境，避免 PowerShell 执行策略问题。

先运行不联网、不写 WPS 的演示：

```powershell
.\.venv\Scripts\python.exe -m etd_sync --demo
```

首次配置：

```powershell
Copy-Item .env.example .env
notepad .env
```

将你自己的 WPS webhook、Token、工作表名称填入 `.env`。这些值不会随 Git 克隆；从原电脑私下迁移，或在 WPS 中重新配置。

> `.env` 如果指向正式共享表格，网页上的“手动同步数据”会实际写入正式 WPS。开发测试建议使用单独测试表格和 Token。

启动网页：

```powershell
.\.venv\Scripts\python.exe start_web.py
```

也可以双击 `启动网页.cmd`，它优先使用项目的 `.venv`。访问 `http://127.0.0.1:8000`，服务窗口保持打开。

## 配置说明

| 配置项 | 含义 |
|---|---|
| `WPS_WEBHOOK_URL` | AirScript 同步接口，结尾是 `/sync_task`，不能用分享链接 |
| `WPS_API_TOKEN` | 对应脚本的 API Token，仅放在 `.env` |
| `WPS_SHEET_NAME` | 底部工作表标签的完整名称 |
| `EVERGREEN_NUMBER_TYPE` | `booking` 订舱号，或 `bl` 提单号；整张表统一 |
| `QUERY_CONCURRENCY` | 网页查询并发数，1–3，默认2 |
| `QUERY_INTERVAL_SECONDS` | 查询开始时间的全局最小间隔，默认1秒 |
| `DATE_YEAR` | 旧版“月.日”文本的年份，建议直接使用完整日期 |
| `HEADLESS` | 命令行查询是否隐藏浏览器；网页版始终后台运行 |

WPS 第1行为表头：A列提单号/订舱号，B列 `ETD（原BC）`，C列 `Valid to`，D列 `ETD` 或 `最新ETD`。单号存文本，日期使用 `YYYY-MM-DD` 或真实日期单元格。完整对接见 [WPS 文档](docs/WPS.md)。

## 数据保存与跨电脑使用

- `data/console.sqlite3`：本环境的订单快照、任务与历史记录。
- WPS：共享表格里的单号、原始 ETD 和最新 ETD。
- GitHub：程序与文档，**不保存业务数据库、Token、日志、依赖目录或密码**。

克隆仓库不会自动同步数据库。开发电脑各有本地数据库；要查看相同线上记录，应连接同一台云服务器。

已有云端用户无需安装编程环境：将 `deploy/cloud-server.example` 复制为同目录的 `cloud-server.local`，第一行填写服务器公网 IP，再双击 `deploy/访问云端.cmd`。通过专用 SSH 账号验证后访问 `http://127.0.0.1:18000`，窗口保持打开。服务器地址和密码由管理员私下提供。

本机 `8000` 是本地开发服务；`18000` 是加密转发到云端的入口。不要混淆开发数据和线上数据。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_bridge.cjs
node tests/test_console_model.mjs
node --check etd_sync/static/console.js
```

上述测试使用模拟数据，不连接正式 WPS，也不写正式订单。

```powershell
# 离线网页交互测试：临时8001端口、模拟数据
.\.venv\Scripts\python.exe tests/browser_check.py

# 读取正式配置、访问真实官网的只读性能对比（不会写 WPS）
.\.venv\Scripts\python.exe tests/benchmark_live.py --limit 3
```

GitHub Actions 在 push / pull request 时运行离线 Python 与 JavaScript 检查，不使用 WPS 凭证。

## 目录结构

```text
etd_sync/
  web.py                 Web API 与服务启动
  service.py             后台任务与同步流程
  storage.py             SQLite、恢复与快照缓存
  orders.py              订单合并、选中目标、历史筛选
  evergreen.py           浏览器会话、查询、结果页ETD提取
  batch.py               有界并发、全局节流、串行处理结果
  wps.py                 WPS AirScript HTTP客户端
  dates.py               日期解析与更新判定
  __main__.py            命令行入口
  templates/index.html   界面结构
  static/                样式、DOM交互与纯展示模型（console-model.mjs）
wps/etd_bridge.js         粘贴到WPS的配套脚本
tests/                   离线测试、网页测试与只读实测
deploy/                  部署、访问脚本、打包与备份
docs/                    配置、开发与交接文档
.env.example             无凭证的配置示例
start_web.py             本地启动入口
```

## 当前边界

一次仅运行一个服务进程/同步任务，不支持多副本部署。不同任务之间、不同开发电脑之间也不要同时写同一张正式表格。查询失败保留旧日期；写入超时可能已被 WPS 接收，应重新读取确认，不能简单认定未修改。

官网结构、访问限制或 WPS 权限变化时可能需要维护查询器。仓库不包含原始入货通知、真实订单截图或完整聊天历史。继续开发请从 [HANDOFF.md](docs/HANDOFF.md) 开始。

历史变更页仅展示成功写回且最新 ETD 晚于该次读取的 Valid to 的记录；不再显示同步任务列表。Valid to 缺失、无效或旧记录未采集该字段时不展示。启用前需更新 WPS 中的 `wps/etd_bridge.js` 脚本。

WPS 的 D 列之后还需添加唯一的“当前状态”列。手动同步后按北京时间更新 ETD未变更 / ETD已变更 / 托班到下一批次 / 已完成；状态单独变化不会新增 ETD 变更历史，详见 [WPS 规则](docs/WPS.md#当前状态手动同步时更新)。

支持单票与勾选同步：可输入 WPS 完整单号、点击行内“单票同步”，或勾选后点击“同步选中订单”。原“手动同步数据”仍同步全部订单。指定同步先重新读取 WPS，只查询和写回目标订单。
