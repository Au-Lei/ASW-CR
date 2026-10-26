# Ubuntu 云端运行与维护

## 当前实际部署方式

用户反馈已在阿里云轻量应用服务器运行成功：Ubuntu 24.04，2核2GB，**Python虚拟环境＋systemd**。此前Docker镜像下载因Docker Hub连接超时未完成，随后改用原生服务。本次GitHub上传不会自动更新服务器。

| 项目 | 当前约定 |
|---|---|
| 应用目录 | `/opt/etd` |
| Python环境 | `/opt/etd/.venv` |
| systemd服务名 | `etd-sync` |
| 服务运行账号 | `etd-sync`，不可登录shell |
| 应用监听 | `127.0.0.1:8000` |
| 正式配置 | `/opt/etd/.env`，仅后台读取 |
| 数据库 | `/opt/etd/data/console.sqlite3` |
| 浏览器目录 | `/opt/etd/browsers` |
| 业务访问账号 | `etd-viewer`，只允许转发到应用端口 |
| 客户端入口 | SSH连接建立后的 `http://127.0.0.1:18000` |

公网IP、管理员密码、访问密码和主机指纹不在本仓库。没有配置域名、公开HTTPS入口或独立网页账号体系。

## 一般用户在另一台电脑使用

Windows需要OpenSSH客户端，不需要Python。下载 `访问云端.cmd` 与 `cloud-server.example`，将后者复制/重命名为同目录的 `cloud-server.local`，第一行填写管理员提供的实际公网IP或主机名。

双击脚本，首次核对主机指纹后确认，输入专用etd-viewer密码。脚本建立加密隧道并打开浏览器。连接窗口需保持打开。所有使用者看到相同的云端数据，也都有同步权限。

原电脑已有私密 `cloud-server.local`，未提交Git。如向同事提供访问工具，应连同该地址配置文件一并私下发送；不要提供admin/root密码或WPS Token。

## 管理员查看状态

在服务器终端执行：

```bash
sudo systemctl status etd-sync --no-pager
sudo journalctl -u etd-sync -n 50 --no-pager
curl -fsS http://127.0.0.1:8000/api/state >/dev/null
```

运行记录可能包含业务单号，分享报错前确认没有敏感内容。

## 首次安装到另一台Ubuntu 24.04服务器

先将源码放到 `/opt/etd`，配置好服务器专用.env；再执行：

```bash
sudo bash /opt/etd/deploy/install_native_ubuntu.sh
```

脚本安装Python、浏览器与系统依赖，创建服务用户，并启用systemd自动启动。实际网络下载速度依环境而定。已有服务运行时脚本会拒绝安装，不应该拿它当自动更新工具。

需要提供SSH业务访问时，由管理员执行：

```bash
cd /opt/etd
sudo bash deploy/configure_viewer.sh
```

密码由管理员亲自在终端设置。该脚本只用于首次创建etd-viewer；同名账号/配置已存在时不覆盖。既有服务器不要重复运行。

## 数据备份

使用最新版仓库的备份脚本：

```bash
cd /opt/etd
sudo -u etd-sync .venv/bin/python deploy/backup.py --data-dir /opt/etd/data
```

通过SQLite backup API获取运行期间的一致副本，执行完整性检查。结果在 `/opt/etd/data/backups/`。管理员还应将备份复制到另一台机器或可靠存储；仅放在同一块服务器磁盘上不能防止整机损坏。WPS数据与本地任务历史是两份不同的数据来源，都应各自维护。

如果服务器上仍是最初上传的旧备份脚本，需要先只上传新的 `deploy/backup.py`，再使用 `--data-dir` 参数；旧版仅支持Docker路径。

## 更新程序，保留线上数据

先等当前同步结束，做数据库备份。不要在新的Git克隆中复制正式data目录来替换线上库，也不要把 `build_bundle.py` 产生的初次迁移数据库包用于覆盖更新。

将已测试的代码克隆到单独目录，例如 `/opt/etd-source`（首次由管理员执行；已有目录则用git pull）：

```bash
sudo git clone https://github.com/Au-Lei/ASW-CR.git /opt/etd-source
```

确认取得希望发布的提交，再用明确的文件范围更新：

```bash
sudo systemctl stop etd-sync
sudo cp -a /opt/etd-source/etd_sync/. /opt/etd/etd_sync/
sudo cp /opt/etd-source/requirements.txt /opt/etd/requirements.txt
sudo cp /opt/etd-source/deploy/backup.py /opt/etd/deploy/backup.py
sudo /opt/etd/.venv/bin/python -m pip install -r /opt/etd/requirements.txt
sudo env PLAYWRIGHT_BROWSERS_PATH=/opt/etd/browsers /opt/etd/.venv/bin/python -m playwright install chromium
sudo chmod -R a+rX /opt/etd/browsers
sudo systemctl start etd-sync
sudo systemctl status etd-sync --no-pager
```

这是一份人工发布顺序：任一步失败先排错，不继续假定成功；若更新浏览器时提示缺系统依赖，可再运行 `playwright install-deps chromium`。不要复制.env或data，保留原来的配置、运行用户和权限。当前没有正式回滚/数据库迁移框架，较大版本升级应先在测试环境核对。

## Docker方案

仓库保留Dockerfile和compose.yaml，端口仅绑定主机回环地址。备用步骤见 [DOCKER.md](DOCKER.md)。不要同时启动原生服务与容器，也不要让两套服务共用正式数据库写入。Docker Hub不可达时，优先使用上述已经跑通的原生方式。
