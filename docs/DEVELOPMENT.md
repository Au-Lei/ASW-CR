# 换电脑继续开发

## 0. 在另一台电脑的 Codex 继续

当前开发分支为 `codex/local-improvements`，业务版本为 0.3.0。先按下文克隆并打开 ASW-CR 文件夹，再让新电脑的 Codex 阅读根目录 `AGENTS.md` 与本指南。代码、测试、金山脚本及交接文档随 Git 同步；聊天记录、私密配置和本地历史库不会自动同步。

已有仓库时，先确认没有需要保存的未提交修改，再执行：

```powershell
git fetch origin
git switch codex/local-improvements
git pull --ff-only origin codex/local-improvements
```

如果本地还没有该分支，用 `git switch --track origin/codex/local-improvements` 替代第二行。不要强制重置或覆盖另一台电脑未提交的工作。

## 1. 准备环境

本项目为Python后端＋原生HTML/CSS/JavaScript，不需要npm构建、React或前端开发服务器。

- Git：克隆、提交和同步代码。
- Python 3.12：推荐与当前开发基线一致。
- Node.js：可选，用于JavaScript测试。
- 编辑器：任选你习惯的编辑器。

在PowerShell里执行：

```powershell
git clone --branch codex/local-improvements --single-branch https://github.com/Au-Lei/ASW-CR.git
cd ASW-CR
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m etd_sync --demo
```

若Windows只有 `py` 命令，第一步改用 `py -3.12 -m venv .venv`；后面的虚拟环境路径保持不变。无需执行Activate.ps1。

### macOS / Linux

安装 Git 和 Python 3.12 后，在终端执行（已克隆则直接进入项目目录）：

```bash
git clone --branch codex/local-improvements --single-branch https://github.com/Au-Lei/ASW-CR.git
cd ASW-CR
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m etd_sync --demo
```

启动网页用 `.venv/bin/python start_web.py`，访问 `http://127.0.0.1:8000`；终端中按 Ctrl+C 停止服务。
首次配置可用 `cp .env.example .env`，再用编辑器填写自己的配置。未填写配置也能运行离线测试；CLI 演示不读写 WPS。
Linux 若缺少浏览器系统库，按 [Ubuntu 部署说明](../deploy/README.md) 安装。

离线验证：

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_bridge.cjs
node tests/test_console_model.mjs
node --check etd_sync/static/console.js
```

后续文档中的 `.venv\\Scripts\\python.exe`，在 macOS / Linux 上替换为 `.venv/bin/python`。

## 2. 迁移私密配置

仓库只提供 `.env.example`。以下内容被Git排除，不会自动下载：

| 文件或目录 | 处理方式 |
|---|---|
| `.env` | 原电脑通过私密方式传到新电脑项目根目录，或重新配置WPS |
| `deploy/cloud-server.local` | 需要访问线上时，按example创建，填写实际公网IP |
| SSH访问密码、主机指纹 | 由管理员私下提供，不写入仓库 |
| `data/console.sqlite3` | 开发一般不需要复制正式库；如确需迁移，使用一致备份 |
| `.venv`、`.runtime` | 不复制，在新电脑重新安装依赖 |
| `logs`、`release` | 不随Git迁移 |

如果没有 `.env`，可以先看演示、运行离线测试及查看网页框架；真实读写会提示未配置。

`.env` 指向正式WPS时，本地同步也会修改正式WPS。最好复制一个测试文档，粘贴 `wps/etd_bridge.js`，为测试脚本生成独立Token，避免开发过程影响业务。

## 3. 启动开发版

```powershell
.\.venv\Scripts\python.exe start_web.py
```

访问 `http://127.0.0.1:8000`，或双击“启动网页.cmd”。这不是线上数据入口。线上访问脚本使用18000端口。

后端没有热重载：修改Python代码或页面模板后，先等当前同步结束，再关闭服务窗口并重新启动；刷新页面。仅修改CSS/JS一般刷新即可。

## 4. 验证代码

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_bridge.cjs
node tests/test_console_model.mjs
node --check etd_sync/static/console.js
```

不访问真实WPS。网页测试可以额外运行：

```powershell
.\.venv\Scripts\python.exe tests/browser_check.py
```

它使用临时数据库和模拟订单，自动选择空闲本机端口；截图写入被忽略的 `.impeccable/review/`。需要已安装Chromium。

`tests/benchmark_live.py` 会读取 `.env`、访问真实官网，请仅在明确需要实测时执行。

## 5. 日常Git操作

先拉取更新，再创建自己的开发分支：

```powershell
git pull --ff-only
git switch -c codex/improve-etd
```

修改、测试后：

```powershell
git status
git diff
git add README.md docs etd_sync tests
git diff --cached
git commit -m "Describe the change"
git push -u origin codex/improve-etd
```

根据实际修改选择文件，不要强制添加 `.env` 或数据库。可以在GitHub发起Pull Request，检查后合并到main。GitHub身份验证使用浏览器登录或你自己的凭证，不要在Git远程URL里嵌入Token。

离开旧电脑前先提交并推送。新电脑上运行 `git pull --ff-only` 获取已提交的代码，未提交内容不会自动出现。

## 6. 给下一次协作的说明

可以复制下面这段作为继续开发时的开场：

> 请继续开发 ASW-CR，使用 codex/local-improvements 分支。先阅读 AGENTS.md、README.md、docs/HANDOFF.md、docs/DEVELOPMENT.md、docs/PORTS-UPGRADE.md 和 docs/LIVE-INTEGRATION.md，核对 git status，再创建本机虚拟环境、安装 requirements.txt 与 Playwright Chromium，并运行 Python、AirScript 模拟和前端离线测试。当前版本 0.3.0 已实现港口同步、备注搜索、新表头映射和 Windows 打包，正式联调已在 2026-10-28 完成；不要重复初始化数据库或覆盖人工字段。缺少 .env 时使用离线演示，真实配置由我另行提供。完成环境检查后继续实现我指定的需求；不要把凭证或业务数据提交到 GitHub，也不要自动部署或修改真实 WPS。

仓库并不包含聊天历史，但HANDOFF记录了业务约定、技术边界和已完成的决策。

## 7. 线上发布前

本地测试通过，不等于云端已更新。云端目录是 `/opt/etd`，服务名是 `etd-sync`。发布步骤见 [部署说明](../deploy/README.md)。不要用本机数据库或首次迁移包覆盖服务器现有data目录。

重构后的模块职责与维护约定见 [ARCHITECTURE.md](ARCHITECTURE.md)。前端使用浏览器原生模块，部署时完整复制 static 目录（包括 `.mjs` 文件），无需 npm 构建。
