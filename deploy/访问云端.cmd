@echo off
chcp 65001 >nul
set "ETD_SERVER="
if not exist "%~dp0cloud-server.local" (
  echo 请先复制 cloud-server.example 为 cloud-server.local，填写服务器公网 IP。
  pause
  exit /b 1
)
set /p "ETD_SERVER="<"%~dp0cloud-server.local"
powershell.exe -NoProfile -Command "if($env:ETD_SERVER -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$'){exit 1}"
if errorlevel 1 (
  echo 服务器地址格式错误，请检查 cloud-server.local。
  pause
  exit /b 1
)
echo 长荣 ETD 云端访问
echo 请输入管理员单独设置的 etd-viewer 访问密码。不要使用 root 密码。
echo 首次连接请将显示的主机指纹与管理员提供的指纹核对。
echo 连接成功后浏览器会自动打开。保持此窗口打开，关闭即断开连接。
start "" /b powershell.exe -NoProfile -Command "$u='http://127.0.0.1:18000'; for($i=0;$i -lt 90;$i++){try{$r=Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 1;if($r.StatusCode -eq 200 -and $r.Content.Contains('ETD')){Start-Process $u;exit}}catch{};Start-Sleep -Milliseconds 1000}" >nul 2>&1
ssh.exe -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:18000:127.0.0.1:8000 "etd-viewer@%ETD_SERVER%"
if errorlevel 1 pause
