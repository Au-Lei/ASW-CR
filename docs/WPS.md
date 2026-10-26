# WPS配置、业务规则与排错

## 表格布局

使用普通共享电子表格，不是多维表格。第一行为表头：

| 列 | 表头 | 用途 |
|---|---|---|
| A | 提单号、订舱号或单号 | 按文本保存，不丢前导零 |
| B | ETD（原BC）或ETD（原始） | 入货通知日期，系统不覆盖 |
| C | Valid to | 当前不用于价格/跨周计算 |
| D | ETD或最新ETD | 系统更新完整日期文本 |

表头支持部分空格及全半角括号兼容。日期使用完整 `YYYY-MM-DD` 或真实表格日期。旧月日文本需要明确DATE_YEAR；小数10.21不会被猜成10月21日。

## AirScript安装

在目标表格新建JavaScript AirScript，把 `wps/etd_bridge.js` 全部复制进去并保存。在编辑器生成脚本Token并取得webhook地址。Python调用同步接口 `/sync_task`；若复制的是异步 `/task`，改为同路径的 `/sync_task`。

在项目根目录的.env设置WPS_WEBHOOK_URL、WPS_API_TOKEN及底部标签WPS_SHEET_NAME。文档分享链接不能代替webhook，文档顶部标题不能代替底部工作表标签。

[官方同步执行API](https://airsheet.wps.cn/docs/en-US/apitoken/api.html)、[脚本Token指引](https://airsheet.wps.cn/docs/en-US/apitoken/intro.html)。

## 比较与更新

| 情况 | 行为 |
|---|---|
| 官网日期不同于原始日期、也不同于D列 | 写入D列 |
| 官网日期等于原始日期，D为空 | 不写 |
| 官网日期与D列一致 | 不重复写 |
| 官网恢复原始日期，D仍有延期旧值 | D更新为恢复后的日期 |
| 查询失败、日期无效或重复单号 | 该票失败，旧日期保留 |
| 写入超时/校验失败 | 写入待确认，重新读取WPS |

写回脚本按单号重新定位，核对B/D原值，然后写入D列并读回确认。查到有效ETD不等于成功写入，网页仅把后者计为已更新。

## 逐步联调

```powershell
.\.venv\Scripts\python.exe -m etd_sync --read-only
.\.venv\Scripts\python.exe -m etd_sync --limit 1
.\.venv\Scripts\python.exe -m etd_sync --apply --limit 1
```

前两步不写WPS；第三步实际写入。网页版“手动同步数据”直接执行读取、查询、写回，没有额外预览确认。

## 常见问题

- 工作表不存在：检查底部标签名是否完整一致。
- 表头不匹配：按上表核对A/B/D，更新的本地脚本也需要重新粘贴到WPS保存。
- 日期解析失败：改用完整年月日，不要使用数字小数表示月日。
- 无官网结果：核对到底是订舱号还是提单号，检查EVERGREEN_NUMBER_TYPE。
- 单号重复：人工确认是否同票多行，当前程序不会猜测要写哪一行。
- 写入待确认：先读取核对真实WPS值，不要立即反复同步。
- 官网超时或验证码：稍后重试或人工查询，不降低提取校验去强行写回。
- HEADLESS=false无可见浏览器：此配置只作用于CLI；Web服务始终后台查询。

查询器按Port of Loading行与Estimated Departure Date列定位，并处理合并列；不能直接使用预计到港或预计装船列代替ETD。
