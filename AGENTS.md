# ASW-CR 开发约定

## 开始工作

- 最新业务版本为 0.3.0，开发分支是 `codex/local-improvements`；先查看 `git status` 与当前分支，保留已有修改，不重置工作区。
- 先读 `README.md`、`docs/DEVELOPMENT.md`、`docs/HANDOFF.md`。业务升级与正式联调记录分别在 `docs/PORTS-UPGRADE.md`、`docs/LIVE-INTEGRATION.md`，架构见 `docs/ARCHITECTURE.md`。
- 本项目是 Python 3.12 / Flask / Waitress / Playwright / SQLite 加原生 ES modules，不需要 npm 构建。Node.js 用于测试；修改页面时保留已有设计体系。

## 本机环境

Windows：`py -3.12 -m venv .venv`，随后使用 `.venv\Scripts\python.exe`。
macOS/Linux：`python3.12 -m venv .venv`，随后使用 `.venv/bin/python`。

安装 `requirements.txt`，再执行 `python -m playwright install chromium`；这里的 python 指虚拟环境解释器。`python -m etd_sync --demo` 可离线演示，`python start_web.py` 启动本机网页。
构建 Windows 版另需 `requirements-desktop.txt`，必须在 Windows x64 构建或使用 `.github/workflows/windows-desktop.yml`；具体步骤见 `docs/WINDOWS.md`。

## 业务边界

- 原始 ETD、Valid to、人工备注不覆盖；按唯一表头识别字段，不恢复固定列号写法。
- 起运港取 Port of Loading，目的港取 Port of Discharge，ETD 取装货港 Estimated Departure Date，不用交货地或到港日代替。
- 港口缺失保留旧值，歧义结果拒绝写入。仅港口更新不计为 ETD 更新、不标黄、不生成 ETD 历史。
- 历史仅展示成功 ETD 变更且新日期严格晚于当次 Valid to 的记录，保留当时快照。北京时间今天严格晚于最新 ETD 才算已完成。
- 保留全量/单票/勾选同步、写前原值比较、写后确认和串行写回。不要默认添加定时任务或自动价格判断。

## 验证与数据

使用虚拟环境运行 `python -m unittest discover -s tests -v`，再运行 `node tests/test_bridge.cjs` 与 `node --test tests/test_console_model.mjs`。页面变化另运行 `python tests/browser_check.py`，桌面变化运行 `python start_desktop.py --self-test <临时结果路径>`。这些离线检查不应访问真实 WPS。

不要将 `.env`、Token、服务器凭证、数据库、真实订单网页或 `.impeccable/live/` 提交到 Git。没有私密配置时继续离线开发，无须索取或猜测凭证。真实 WPS 写入或部署按用户授权范围执行。

不要在正在运行的正式数据库上另建 Console 实例：初始化会恢复中断任务。测试使用临时数据库；不要清空或用测试库覆盖用户历史。Git 推送不会自动更新金山脚本、云服务或其他电脑的配置。
