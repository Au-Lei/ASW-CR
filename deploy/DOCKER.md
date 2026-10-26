# Docker备用方案（历史部署参考）

实际已采用原生venv＋systemd，优先阅读 [当前部署说明](README.md)。本文保留Docker初次迁移方案；不要与原生服务同时运行。服务器地址为占位符，实际地址通过私密配置提供。

# 阿里云 Ubuntu 24.04 部署（无域名版）

目标：截图中的轻量应用服务器，公网 IP `YOUR_SERVER_IP`，Ubuntu 24.04，2核2GB。当前目录仅准备部署文件，不代表已经登录或部署到服务器。

## 访问方式与数据

程序长期运行在服务器，所有电脑查看服务器的同一数据库，WPS 也保持同一份。数据库目录挂载在 `/opt/etd/data`，代码更新和容器重启不会清空它。不要删除这个目录，也不要在更新时覆盖已有数据库。

没有域名时，这一版采用 SSH 加密连接：Windows 电脑双击 `访问云端.cmd`，输入专门的访问密码，浏览器打开 `http://127.0.0.1:18000`。这个地址通过加密通道访问云端，不是本机原来的8000端口；每台电脑看到相同的云端数据。访问窗口需要保持打开。客户端需有 Windows OpenSSH（当前电脑已经安装）。

8000端口只监听服务器本机，不向公网放行。只需确保访问者能到达SSH端口22。可在阿里云轻量服务器“防火墙”里按使用者来源地址放行。已有服务器SSH配置和其他业务先核对，不重置系统、不关闭原有服务。

客户使用独立的 `etd-viewer` 账号，不共享root密码。该账号只能转发到本应用，不能登录服务器命令行或传文件。当前所有访问者查看同一数据并均可同步，没有区分只读/管理员角色。以后配置域名和 HTTPS 后，可改为浏览器直接登录。

## 第一步：初次迁移

本机打包命令（已为本次部署生成）：

```powershell
python deploy/build_bundle.py
```

生成 `release/etd-server.zip`：包含代码和现有数据库的一致快照，不包含 `.env` 中的 WPS 凭证。只用于**首次部署**，现有云端数据库不可用旧快照覆盖。之后的程序更新应单独上传代码、保留服务器data目录。

确认服务器的SSH用户名和认证方式后，在本机 PowerShell 上传。当前服务器登录用户为admin，以下以admin密码登录为例；若服务器使用密钥，则由管理员改用现有密钥认证，不在聊天中提供私钥：

```powershell
scp "C:\path\to\ASW-CR\release\etd-server.zip" admin@YOUR_SERVER_IP:~/etd-server.zip
scp "C:\path\to\ASW-CR\.env" admin@YOUR_SERVER_IP:~/etd-server.env
```

首次连接时将SSH主机指纹与服务器控制台中 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 的结果比对，再确认。上传密码直接在本机输入，不发给他人。

然后在阿里云“远程连接”的服务器终端执行（需root或sudo权限）：

```bash
sudo apt-get update
sudo apt-get install -y unzip
sudo install -d -m 755 /opt/etd
sudo test ! -e /opt/etd/data/console.sqlite3
```

最后一行若报错，说明已有数据库，先停止迁移，不要解压覆盖。确认目录为新部署后继续：

```bash
sudo unzip -n "$HOME/etd-server.zip" -d /opt/etd
sudo install -o root -g root -m 600 "$HOME/etd-server.env" /opt/etd/.env
rm -- "$HOME/etd-server.env"
cd /opt/etd
sudo bash deploy/install_docker_ubuntu.sh
sudo install -d -o 10001 -g 10001 -m 750 data logs
sudo chown -R 10001:10001 data logs
sudo docker compose config --quiet
sudo docker compose up -d --build
sudo docker compose ps
```

首次下载依赖和浏览器可能较慢。脚本使用 Docker 官方软件源；发现现有Docker时保留，不卸载已有容器组件。如果报下载、内存或已有软件冲突错误，保留报错进一步排查，不重装服务器。2GB内存建议先保持2票并发，出现浏览器内存不足时可改 `.env` 的 `QUERY_CONCURRENCY=1` 后执行 `sudo docker compose up -d --force-recreate`。

在服务器测试：

```bash
curl -fsS http://127.0.0.1:8000/api/state >/dev/null
```

命令无报错表示接口可达。再配置仅访问应用的账号：

```bash
sudo bash deploy/configure_viewer.sh
```

按提示设置专门的访问密码，记录输出的主机指纹。脚本只为新建的etd-viewer增加限制，不更改root登录设置；若同名账号或配置已存在就退出，不覆盖。

## 第二步：其他电脑访问

将 `deploy/访问云端.cmd` 单独发给需要使用的同事，并通过合适方式告知独立访问密码和主机指纹；不用发送项目、WPS Token或管理员密码。双击后输入访问密码，连接建立后浏览器会打开。脚本不保存密码。

第一次登录后核对已有订单及历史记录；点击“读取订单”只验证WPS读通，再点击同步。用第二台电脑打开，确认看到同一结果；重启容器后确认记录仍在。

## 数据备份与升级

数据库支持运行期间一致备份，执行：

```bash
cd /opt/etd
sudo docker compose exec -T app python - < deploy/backup.py
```

备份保存在 `/opt/etd/data/backups`。请由管理员另行下载或复制到异机存储；仅保存在同一服务器不能防止整机磁盘丢失。`.env` 也应由管理员妥善保存。

修改配置或更新代码后：

```bash
cd /opt/etd
sudo docker compose up -d --build
```

先等当前同步结束再更新。单个应用容器运行一个进程，暂不启动多副本，否则会破坏当前的任务互斥。Docker restart策略可在系统Docker服务恢复后拉起容器，SQLite数据仍保存在主机data目录。

资料：[Docker Ubuntu安装](https://docs.docker.com/engine/install/ubuntu/)、[Playwright Docker](https://playwright.dev/python/docs/docker)、[阿里云轻量服务器远程连接](https://www.alibabacloud.com/help/en/simple-application-server/user-guide/connect-to-linux-server-remotely)。
