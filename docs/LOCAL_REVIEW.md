# 本地项目梳理与首轮优化

日期：2026-10-26。源码基线：`fd4dec9`。本地开发分支：`codex/local-improvements`。

## 项目在做什么

为海运代理追踪长荣装货港 ETD。网页手动发起任务，从 WPS 读取单号与日期，查询官网，再将确认变化的最新 ETD 写回 D 列。B 列原始 ETD 保留。SQLite 保存本环境的订单状态、任务及历史。

技术栈为 Python 3.12、Flask、Waitress、Playwright、SQLite 和原生 HTML/CSS/JavaScript，无前端构建步骤。

## 代码阅读顺序

1. `etd_sync/dates.py`：日期解析与是否更新的业务规则。
2. `etd_sync/wps.py` 与 `wps/etd_bridge.js`：HTTP 接口、行定位、原值校验和读回验证。
3. `etd_sync/evergreen.py`：浏览器生命周期、官网表头与装货港定位。
4. `etd_sync/batch.py`：有界并发、全局查询节流、串行处理查询结果。
5. `etd_sync/web.py`：任务互斥、同步流程、SQLite 恢复和 Web API。
6. `etd_sync/static/console.js`：轮询、筛选、任务明细与日志。

## 已有基础

- 查询结果按原始索引关联订单，避免并发乱序造成错行写入。
- WPS 写入串行，写前校验原始值、写后读回验证。
- 重复单号和无效日期在查询前跳过，查询失败保留已有日期。
- 服务重启恢复中断状态，接口有 CSRF 与 Host 检查。
- 已有模拟 WPS、日期、并发、备份和网页测试；GitHub Actions 运行离线检查。

## 本轮优化

- 请求校验：`/api/jobs` 对数组、字符串、数字等非对象 JSON 返回 400，避免调用 `.get()` 导致 500。
- CSRF 校验：比较 UTF-8 字节，非 ASCII 的错误令牌也正常返回 403。
- 启动恢复：线程未启动时将已持久化任务标记失败、记录结束时间并释放锁，允许再次发起任务。
- 错误脱敏：启动接口的 RuntimeError 沿用现有脱敏逻辑，避免将配置值直接返回页面。
- 回归测试覆盖上述场景；补充 macOS / Linux 虚拟环境、演示、启动与测试说明。

## 验证结果

- 原始代码的 19 项 Python 测试通过；新增的三个回归场景在原代码上复现失败。
- 修复后的 22 项 Python 测试全部通过。
- `node tests/test_bridge.cjs` 与 `node --check etd_sync/static/console.js` 通过。
- `tests/browser_check.py` 通过：读取、同步、进度、统计、筛选、错误、搜索、历史及手机布局。
- CLI 离线演示、`pip check`、`git diff --check` 与 `git fsck --full` 通过。
- 本地 Waitress 服务已在 `http://127.0.0.1:8000` 启动；尚未配置真实 WPS 凭证。

## 后续建议顺序

1. **失败订单重试**：重新读取 WPS 并校验后，仅查询本次失败的单号；写入待确认的订单先核对 WPS，不能直接重放写入。
2. **任务取消**：停止发起新查询，等待已开始的写入确认，明确区分已完成与未处理订单。
3. **数据量优化**：先测量大量订单下的轮询大小、SQLite 快照耗时与页面渲染，再决定分页、增量响应或表结构调整。
4. **部署可复现性**：记录验证过的依赖版本，建立升级前备份和升级后冒烟检查流程。

独立登录与操作人审计应在决定开放公网访问时一起设计。当前继续使用单进程服务和 SSH 隧道。

## 本地环境与业务数据

本地目录：`/Users/au-lei/Documents/ChatGPT/ASW-CR`。使用项目 `.venv`；启动命令为 `.venv/bin/python start_web.py`。

Git 直连失败后，通过 GitHub API 获取源码归档与提交元数据。逐文件校验 45 个 blob，确认目录树及原始提交哈希一致后恢复 Git 对象与分支。该提交没有父提交，因此保留了仓库现有的全部提交历史。

仓库未提供 `.env` 或正式业务数据库；本次验证使用模拟订单和临时数据库，不连接正式 WPS，也不更新云端服务。
