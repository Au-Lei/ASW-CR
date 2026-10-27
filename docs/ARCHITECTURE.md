# 代码结构与维护约定

本轮重构以 2026-10-27 已实现的功能为基线。保留 Python/Flask、原生前端、WPS AirScript 和 SQLite JSON 数据格式，不增加前端构建或数据库迁移步骤。

## 后端职责

| 模块 | 负责 | 不应放入 |
|---|---|---|
| `web.py` | HTTP 参数、CSRF、响应头、Waitress 启动 | SQL、订单计算、浏览器查询 |
| `service.py` | 任务互斥、生命周期、查询调度、串行处理和写回结果 | Flask 路由、SQL、页面展示 |
| `storage.py` | SQLite 事务、持久化、中断恢复、快照缓存 | 网络请求、状态业务判断 |
| `orders.py` | 读取结果合并、目标单号校验、历史记录筛选 | 数据库连接、线程、页面元素 |
| `dates.py` | 日期解析、ETD 更新条件、四种当前状态的优先级 | WPS 或 Flask 调用 |
| `batch.py` | 有界并发、全局启动间隔、串行结果回调 | 具体订单业务规则 |
| `wps.py` / `evergreen.py` | 各自的外部服务协议和资源管理 | 页面和历史展示规则 |

调用方向是 `web → service → orders / storage / batch / 外部客户端`，业务模块不反向导入 `web`。`from etd_sync.web import Console` 继续兼容原有调用方；测试内部时钟或线程时应定位 `etd_sync.service`。

`ConsoleStore` 是单进程服务的唯一存储实例。订单处理结果与任务进度在同一事务提交；失败时一起回滚。空闲轮询复用快照，所有存储操作都会使缓存失效，返回值为独立副本。同步前只读取订单快照，避免无谓计算历史。

## 前端职责

- `console-model.mjs`：不依赖 DOM 的展示数据计算，包括日期格式、查询结果合并、筛选、重复单号计数、日志生成；通过 Node 测试。
- `console.js`：网络请求、用户操作和 DOM 更新。入口 `render()` 分派到概览、订单、历史和日志四个渲染函数。
- `console.css`：现有视觉和响应式布局；删除历史任务列表遗留的无效样式。
- 模板使用浏览器原生 ES Module 加载脚本，无 npm 构建；部署应完整复制 `etd_sync/`，包括 `.mjs` 文件。

## 保留的功能约束

- 全量、单票及勾选同步使用同一条同步流程，执行前重新读取 WPS。
- 选中单号不存在则不发起查询；重复单号不猜测行；并发结果按原始索引归属。
- WPS 写回串行，校验原始值，写回失败提示待确认；失败不伪装为更新成功。
- 当前状态优先级：已完成 → 托班到下一批次 → ETD已变更 → ETD未变更；北京时间今天晚于最新 ETD 才完成。
- 历史页仅展示成功变更且最新 ETD 超过当次 Valid to 的记录；旧记录缺少字段不推测。
- ETD 变更后的浅黄色背景由既有 WPS 脚本执行，本轮不修改脚本协议。
- 原 API、启动命令、`.env`、数据库表和业务数据路径保持兼容。

## 修改后的验证

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_bridge.cjs
node tests/test_console_model.mjs
node --check etd_sync/static/console.js
.venv/bin/python tests/browser_check.py
```

Windows 使用 `.venv\Scripts\python.exe` 替换 Python 路径。浏览器测试使用临时数据库和模拟订单；默认端口 8001，须空闲。

本轮增加了快照缓存失效、调用方修改隔离、事务失败回滚、旧格式数据库恢复的测试，以及前端选择同步结果归属、旧结果失效、筛选、日志时间等测试。GitHub Actions 同步运行新增的前端模型测试。

## 后续优化边界

业务规模增加后，可测量全部历史的加载成本，再考虑历史分页或独立索引表；当前缓存减少空闲轮询的重复工作，但写入后的首次快照仍需计算历史。大量订单的前端渲染也应先测量再优化。本轮不引入多进程、多副本或新的数据库结构。

新增功能优先复用现有流程：日期规则放 `dates.py`，订单筛选放 `orders.py`，持久化放 `storage.py`，前端展示计算放 `console-model.mjs`。避免在 HTTP 路由或大渲染函数里继续累积业务分支。
