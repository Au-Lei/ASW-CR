#!/usr/bin/env bash
# Opt-in setup: an account that can forward only to this application, no shell.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo 'Run with sudo.' >&2
  exit 1
fi
if id etd-viewer >/dev/null 2>&1 || [[ -e /etc/ssh/sshd_config.d/00-etd-viewer.conf ]]; then
  echo 'Viewer account/config already exists; no changes made.' >&2
  exit 1
fi
/usr/sbin/sshd -t
adduser --disabled-password --gecos '' etd-viewer
echo 'Set a dedicated viewer password; do not reuse the server administrator password.'
passwd etd-viewer
install -m 644 /dev/stdin /etc/ssh/sshd_config.d/00-etd-viewer.conf <<'EOF'
Match User etd-viewer
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:8000
    AllowStreamLocalForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    MaxSessions 0
    PasswordAuthentication yes
    KbdInteractiveAuthentication no
Match all
EOF
if ! /usr/sbin/sshd -t; then
  rm -- /etc/ssh/sshd_config.d/00-etd-viewer.conf
  echo 'SSH config check failed; original service was not reloaded.' >&2
  exit 1
fi
systemctl reload ssh
echo 'Viewer account ready. It can only forward to 127.0.0.1:8000; no shell/SFTP.'
echo 'Server host fingerprint (compare on first client connection):'
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
