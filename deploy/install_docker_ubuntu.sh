#!/usr/bin/env bash
# Official Docker apt repository; no removal of existing container runtimes.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker compose version || { echo 'Existing Docker has no Compose plugin. Ask the administrator to install it.'; exit 1; }
  echo 'Existing Docker retained.'
  exit 0
fi
source /etc/os-release
if [[ ${ID} != ubuntu || ${VERSION_ID} != 24.04 ]]; then
  echo 'This helper supports Ubuntu 24.04 only.' >&2
  exit 1
fi
if dpkg-query -W -f='${Status}' docker.io containerd 2>/dev/null | grep -q 'install ok installed'; then
  echo 'An existing container runtime was found; no changes made. Ask the administrator to check conflicts.' >&2
  exit 1
fi
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
if [[ ! -e /etc/apt/sources.list.d/docker.sources ]]; then
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
fi
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
