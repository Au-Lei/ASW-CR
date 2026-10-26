#!/usr/bin/env bash
# Initial native deployment for Ubuntu 24.04, without Docker Hub.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
source /etc/os-release
if [[ ${ID} != ubuntu || ${VERSION_ID} != 24.04 ]]; then
  echo 'This installer supports Ubuntu 24.04 only.' >&2; exit 1
fi
APP=/opt/etd
if [[ ! -s ${APP}/.env || ! -f ${APP}/etd_sync/web.py ]]; then
  echo 'Missing application or .env in /opt/etd; upload and extract first.' >&2; exit 1
fi
if systemctl is-active --quiet etd-sync; then
  echo 'etd-sync already running; stop it after current tasks finish before updating.' >&2; exit 1
fi
if [[ -n $(ss -H -ltn 'sport = :8000') ]]; then
  echo 'Port 8000 already in use; existing service was not changed.' >&2; exit 1
fi
apt-get update
apt-get install -y python3-venv python3-pip
python3 -m venv "${APP}/.venv"
"${APP}/.venv/bin/python" -m pip install --retries 3 --timeout 60 -r "${APP}/requirements.txt"
"${APP}/.venv/bin/python" -m playwright install-deps chromium
PLAYWRIGHT_BROWSERS_PATH="${APP}/browsers" "${APP}/.venv/bin/python" -m playwright install chromium
chmod -R a+rX "${APP}/browsers"
if ! id etd-sync >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$APP" --no-create-home --shell /usr/sbin/nologin etd-sync
else
  [[ $(getent passwd etd-sync | cut -d: -f6) == "$APP" ]] || {
    echo 'Existing etd-sync user has a different home; no service installed.' >&2; exit 1;
  }
fi
install -d -o etd-sync -g etd-sync -m 750 "${APP}/data" "${APP}/logs"
chown -R etd-sync:etd-sync "${APP}/data" "${APP}/logs"
chown root:etd-sync "${APP}/.env"
chmod 640 "${APP}/.env"
cat >/etc/systemd/system/etd-sync.service <<'EOF'
[Unit]
Description=Evergreen ETD WPS console
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=etd-sync
Group=etd-sync
WorkingDirectory=/opt/etd
EnvironmentFile=/opt/etd/.env
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/etd/browsers
ExecStart=/opt/etd/.venv/bin/python -m etd_sync.web
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now etd-sync
for attempt in $(seq 1 20); do
  if "${APP}/.venv/bin/python" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/state',timeout=2)" 2>/dev/null; then
    echo 'SUCCESS: etd-sync is running; existing data is retained in /opt/etd/data.'
    systemctl is-active etd-sync
    exit 0
  fi
  sleep 1
done
echo 'Startup did not pass health check. Run: sudo journalctl -u etd-sync -n 50 --no-pager' >&2
exit 1
