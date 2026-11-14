#!/bin/sh
# Run once on a Linux Docker Compose host, from the studio installation directory.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this installer with sudo.'; exit 1; }
root=$(pwd -P)
test -f "$root/docker-compose.yml"
for tool in docker git python3 systemctl; do command -v "$tool" >/dev/null; done
docker compose version >/dev/null
case "$root" in *[!A-Za-z0-9_./-]*) echo 'Use an installation path without spaces or special characters.'; exit 1;; esac
state=/var/lib/novelvids-update
install -d -m 700 "$state" /run/novelvids-update
if [ -f "$state/status.json" ]; then
  python3 - "$state/status.json" <<'STATUS'
import json, sys
if json.load(open(sys.argv[1]))["phase"] in {"preparing", "draining", "installing", "rolling_back", "recovery_needed"}:
    sys.exit("The existing updater has an unfinished operation.")
STATUS
fi
if [ -f "$state/root" ] && [ "$(cat "$state/root")" != "$root" ]; then echo 'An updater already manages another project.'; exit 1; fi
if [ ! -f "$state/root" ]; then
  for override in docker-compose.override.yml docker-compose.override.yaml compose.override.yml compose.override.yaml compose.yaml compose.yml; do
    [ ! -e "$override" ] || { echo "Custom Compose layout: $override"; exit 1; }
  done
fi
test -z "${COMPOSE_FILE:-}"
[ -z "${COMPOSE_PROJECT_NAME:-}" ] || { echo 'Set a custom Compose project name in the project .env before installation.'; exit 1; }
# Validate host tools before changing the deployment.
docker info >/dev/null
[ -f "$root/release.json" ]
printf '%s\n' "$root" > "$state/root"
sha256sum docker-compose.yml | cut -d" " -f1 > "$state/compose.sha256"
install -m 700 scripts/update/agent.py "$state/agent.py"
cat > /etc/systemd/system/novelvids-update.service <<EOF
[Unit]
Description=NovelVids Docker Compose updater
After=docker.service
[Service]
ExecStart=/usr/bin/python3 $state/agent.py $root
Restart=on-failure
UMask=0077
RuntimeDirectory=novelvids-update
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable novelvids-update.service
systemctl restart novelvids-update.service
if [ ! -e docker-compose.override.yml ]; then
  printf '%s\n' 'services:' '  backend:' '    volumes:' '      - /run/novelvids-update:/run/novelvids-update:ro' > docker-compose.override.yml
  docker compose up -d --build
else
  docker compose up -d
fi
