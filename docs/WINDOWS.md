# 长荣货物追踪 · Windows 免安装版

## 第一次使用

1. 下载 ASW-CR-Windows-x64.zip，右键“全部解压”。不能在压缩包预览窗口直接运行 EXE。
2. 保持 ASW-CR.exe 与 _internal 文件夹在一起，双击 ASW-CR.exe。
3. 首次会出现 WPS 配置窗口。填写同步 webhook（结尾 /sync_task）、脚本 Token、底部工作表标签名，以及 booking / bl 类型；保存后自动打开控制台。
4. 先点击“读取订单”验证配置。确认后再使用全量、单票或勾选同步。

不需要安装 Python、Node.js 或 Chromium，不需要运行命令。程序只监听本机地址，启动时自动选择空闲端口；每次使用请双击 EXE，不要依赖旧端口书签。

程序仍需联网访问 WPS 和长荣官网。“免安装”不代表离线查询。

## WPS 表格准备

A 列为单号，B 列为原始 ETD，C 列为 Valid to，D 列为最新 ETD；D 列之后添加唯一的“当前状态”列。

使用压缩包内的 WPS对接脚本.txt，完整复制到目标金山普通共享电子表格的 AirScript 并保存。文档分享链接不能替代脚本同步 webhook。

Token 仅填写在本地配置窗口，不随安装包分发。不要将自己的配置文件发给无关人员。

## 托盘操作

关闭网页不会退出程序。任务栏右侧托盘（可能在隐藏图标中）有蓝色船形图标，右键可：

- 打开控制台。
- 修改 WPS 配置（无需重启；保存后重新读取订单）。
- 打开数据目录或查看 WPS 对接脚本。
- 退出程序。同步进行中会阻止退出，请等待任务完成。

再次双击 EXE 会打开已有实例，不启动第二个同步服务。配置窗口尚未保存时，再次启动会提示查看原配置窗口。

## 配置、历史与升级

数据保存在当前用户的 %LOCALAPPDATA%\ASW-CR：

- .env：WPS 配置和 Token。
- data\console.sqlite3：订单快照、任务和历史。
- logs\desktop.log：启动错误诊断日志。

升级时先等同步结束，从托盘退出，再解压新版到新的文件夹运行。数据目录独立于程序目录，原配置与历史会保留；不要删除上述用户数据目录。

不同电脑各自有本地历史库；金山表格共享不代表各电脑的历史自动共享。需要所有人查看同一历史时，应继续使用现有云端服务。

源代码开发版的 .env 和数据库不会自动导入 EXE。可在配置窗口重新填写；如需迁移旧数据库，应先关闭两端服务，使用一致备份复制到上述数据目录，不能在同步过程中直接覆盖。

## 使用遇到问题

- 找不到资源：确认完整解压并保留 _internal 文件夹。
- 未打开网页：从托盘点“打开控制台”。
- 启动失败：查看用户数据目录中的 logs\desktop.log。
- WPS 读取失败：核对脚本版本、webhook、Token、工作表标签名。
- 写入待确认：先读取金山表格确认结果，不要反复点击同步。

此版为 Windows x64 包；Mac 继续使用开发版启动方式。安装包未做商业代码签名，Windows 可能显示未知发布者提示，应先确认文件来自本项目发布记录并核对 SHA256。

## 维护者构建方式

GitHub Actions 的 Windows desktop 工作流在 Windows 环境执行：离线回归测试 → 下载 Chromium headless shell → PyInstaller 目录版打包 → 冻结 EXE 的离线网页与浏览器自检 → 上传 ZIP 和 SHA256。

安装包只从明确列出的源码和资源生成，不包含本机 .env、真实业务数据库、日志或服务器配置。配置窗口、托盘、Chromium 和网页资源均随包提供。

本地 Windows 构建：安装 Python 3.12 x64 后执行：

```powershell
python -m pip install -r requirements-desktop.txt
$env:PLAYWRIGHT_BROWSERS_PATH="0"
python -m playwright install chromium --only-shell
python deploy/build_windows.py
```

产物位于 release\ASW-CR-Windows-x64.zip。冻结 EXE 可用 `--self-test 自检结果.json` 执行离线自检；此模式只使用临时数据库和模拟订单，不连接真实 WPS 或长荣官网。
