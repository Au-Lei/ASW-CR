# 长荣船期同步
<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
海运代理业务人员及不会编程的客户，在共享 WPS 表格维护订单。

## Product Purpose
点击一次同步，读取 WPS 单号、查询长荣最新 ETD，更新共享表格并展示修改明细和统计。

## Operating Context
本地网页与 Ubuntu 24.04 云服务器运行。云端采用 Python 虚拟环境与 systemd，浏览器通过 SSH 隧道访问。沿用已验证的 Python、Playwright 和 WPS AirScript 配置。

## Capabilities and Constraints
手动触发，不安排定时任务。显示进度、成功修改、未变化及失败。查询失败保留旧 ETD，写入异常提示结果待确认。凭证仅在后端。一次运行一个同步任务，任务内最多两票默认并发查询、逐票串行写回，历史保存在 SQLite。

## Open Decisions
域名、HTTPS 和独立网页登录尚未配置。现阶段使用专门的 SSH 转发账号，不开放网站到公网。实现采用 Python Web 后端与原生 HTML/CSS/JS。

## Confirmed Visual Direction
用户提供的 HTML 原型是改版视觉依据（原型文件不随仓库分发）。沿用深蓝侧栏、蓝色操作、浅灰背景与白色数据卡片的业务控制台风格；当前视觉规范记录于 `DESIGN.md`。

## 当前状态规则

金山表格新增“当前状态”列；手动同步时按北京时间计算：今天晚于最新 ETD 为已完成，其次最新 ETD 超过 Valid to 为托班到下一批次，其次与原始 ETD 不同为 ETD已变更，否则 ETD未变更。ETD 当天不算完成。ETD 未再次变更也会检查并更新状态；不安排定时任务。网页同时显示当前状态与同步结果。
