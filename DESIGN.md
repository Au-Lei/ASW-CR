---
name: 长荣货物 ETD 追踪系统
description: 用户参考 HTML 所确立的深蓝侧栏与白色数据工作区
colors:
  primary: "#096dce"
  primary-hover: "#085eb2"
  data-blue: "#1677df"
  sidebar-navy: "#001529"
  canvas: "#f0f2f5"
  paper: "#ffffff"
  ink: "#262626"
  muted: "#646970"
  line: "#e8eaed"
  success: "#237b2a"
  error: "#ce333d"
  focus: "#67adf5"
typography:
  metric:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif'
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif'
    fontSize: "16px"
    fontWeight: 600
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif'
    fontSize: "14px"
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif'
    fontSize: "12px"
  log:
    fontFamily: 'Consolas, "Microsoft YaHei", monospace'
    fontSize: "12px"
    lineHeight: 2
rounded:
  control: "4px"
  notice: "6px"
  surface: "8px"
spacing:
  compact: "8px"
  small: "12px"
  medium: "16px"
  gap: "20px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "36px"
  navigation-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    padding: "16px 24px"
  stat-card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.surface}"
    padding: "21px 24px"
  search-input:
    rounded: "{rounded.control}"
    padding: "7px 10px"
  status-updated:
    backgroundColor: "#e6f7ff"
    textColor: "#0967ad"
    rounded: "{rounded.control}"
    padding: "3px 8px"
---

# Design System: 长荣货物 ETD 追踪系统

## Overview

**Creative North Star: "参考 HTML 的业务控制台"**

用户提供的 `2版.html` 是本轮改版的视觉依据。系统采用深蓝导航、浅灰画布、白色统计卡与数据工作区，保持业务表格清晰、操作直接。这一名称用于描述已实现界面，不代表新增品牌口号。

数据状态、同步进度与异常说明优先于装饰。页面呈现后端返回的真实任务和订单结果；尚未同步时保留明确的空状态与占位符。

**Key Characteristics:**
- 深蓝侧栏与白色顶栏形成稳定导航框架。
- 四张白色统计卡提供快速概览。
- 蓝色承载操作和更新结果，绿色与红色表达核对与异常。
- 实时数据、历史变更和系统运行记录分别可达。

## Colors

### Primary

主操作蓝用于同步按钮与选中导航，悬停使用更深的操作蓝。白色按钮文字搭配加深后的主色；数据蓝用于更新数字、链接、筛选与最新日期。颜色值以 frontmatter 为准。

### Neutral

深海军蓝是侧栏底色；浅灰画布托起白色卡片、顶栏与表格工作区。深灰正文与中灰辅助文字建立信息层级，浅灰分隔线组织密集数据。

### Status

绿色用于未变更统计与无需变更标签；蓝色用于已更新和查询中；红色用于失败或中断；黄色标签表示待查询。所有状态均附文字，不单靠颜色区分。写入阶段异常显示“写入待确认”。

**The Verified Update Rule.** 只有写回并验证成功的订单才显示“已更新”；查询失败保留旧值，写入异常提示重新读取确认。

已更新订单行使用浅黄色背景（`#fff3b0`），悬停时为 `#ffe680`，适用于订单列表、同步明细与历史变更。保留文字状态和蓝色最新日期，以便识别更新结果。

## Typography

**Display Font / Body Font:** 系统无衬线字体栈，优先平台 UI 字体，中文回退 Microsoft YaHei。

**Label/Mono Font:** 系统标签沿用无衬线；运行记录使用 Consolas 与中文回退。

### Hierarchy

- **Metric:** 大号统计数字，使用 frontmatter 的 metric 样式与等宽数字特性。
- **Title:** 页标题和区块标题使用 title 样式；品牌文字为 (18px / 650)。
- **Body:** 基准正文使用 body 样式；表格和按钮文字为 (13px)。
- **Label:** 辅助标签主要为 (12px)，统计细节和表格次级说明为 (11px)。
- **Log:** 运行记录使用 log 样式，时间、级别、内容分别呈现。

## Layout

桌面使用固定左侧导航（220px）、同高品牌与顶栏（64px），内容区随侧栏向右偏移。主内容最大宽度（1900px），常规内边距（24px）；宽屏从（1600px）起改为（28px 32px）。概览为四列等分白色卡片，间距（20px）。

实时数据页依次呈现统计、同步进度、操作工具栏、可搜索和筛选的订单表格。历史页仅展示成功变更且变更后 ETD 晚于 Valid to 的记录，包含 Valid to 列，不展示同步任务列表；运行记录页以深色日志面板呈现实际任务结果。

在（1200px）收紧间距；（900px）及以下侧栏缩至（190px），统计改为两列。在（620px）及以下侧栏改为顶部品牌与横向三项导航，隐藏侧栏底部信息，顶栏恢复普通文档流，内容内边距（18px 14px），搜索占满一行，操作按钮高（39px）。表格保留列并横向滚动。

## Elevation & Depth

浅灰画布与白色面板负责主要层次；细边框界定表格和任务面板。阴影轻量辅助分层，避免遮盖业务数据。

### Shadow Vocabulary

- **Header:** `0 1px 4px #00152914`，顶栏与内容的轻分隔。
- **Stat card:** `0 2px 8px #00152907`，统计卡的轻微抬升。
- **Terminal:** `0 4px 12px #00000016`，深色运行记录面板。

## Shapes

控件、搜索框和状态标签使用小圆角；任务通知使用中圆角；卡片、工作区和终端使用大圆角。具体尺度由 frontmatter 的 rounded 定义。导航占满侧栏宽度，桌面选中态以左侧白色内线辅助标识，小屏改为底部白线。图标采用内联 SVG 细线风格。

## Components

### Buttons

主按钮为蓝底白字；次按钮为白底细边框。桌面高度、圆角和内边距见 tokens。悬停改变底色或边框；键盘聚焦使用（3px）浅蓝外轮廓，偏移（3px）。运行或提交期间两个操作均禁用，透明度（0.55），文案对应“正在同步…”或“正在读取…”。

### Chips

结果标签使用淡底、同色细边框与深色文字。订单状态包括已更新、无需变更、失败、查询中、待查询、未查询、已中断。全部订单、已更新、异常订单为文字筛选标签，选中以蓝色文字和底线表现，并同步 `aria-pressed`。

### Cards / Containers

统计区固定四个语义：监控提单总数、ETD 未变更、ETD 已更新、查询 / 写入失败。统计取真实订单、最近同步或选中历史任务。工作区为白底、细边框和圆角，标题、筛选、表格、说明按层组织。

### Inputs / Fields

单号搜索框配细灰边框与搜索图标；输入文字继承正文色。聚焦容器显示（2px）蓝色外轮廓、偏移（2px）。小屏搜索占满可用宽度。

### Navigation

四项导航为“实时数据变更”“历史变更记录”“系统运行记录”“使用说明”，选中项使用操作蓝、白字与 `aria-current="page"`。底部显示 WPS 配置或连接状态；连接失败同时提供错误提示。小屏导航转为顶部两列布局。

### Task Progress / Runtime Log

浅蓝任务面板显示真实任务消息、完成数和最近同步时间。任务状态为运行中、已完成、部分失败、执行失败、已中断；运行期间显示进度条、呼吸状态点。部分失败、执行失败和中断使用红色状态点。无任务时显示准备就绪。

日志深灰底、等宽字体，按时间、级别、消息组织；INFO、SUCCESS、ERROR、WARN 有独立色彩。进度区使用礼貌状态朗读，日志有 `role="log"`。减少动画偏好会关闭动画与过渡，历史明细跳转也不使用平滑滚动。

## Do's and Don'ts

### Do:
- **Do** 沿用用户参考 HTML 确立的深蓝导航、蓝色操作、浅灰画布与白色工作区。
- **Do** 将任务和订单状态同时表达为文字与颜色。
- **Do** 保留键盘焦点、小屏横向表格滚动和减少动画支持。

### Don't:
- **Don't** 把未执行、查询失败或写入待确认显示为已更新。
- **Don't** 将已被本轮参考样式替换的绿色主操作重新作为当前视觉规范。
