#!/bin/sh
# Run once from an existing Docker Compose installation (Linux or Docker Desktop).
set -eu
root=$(pwd -P)
test -f "$root/docker-compose.yml"
docker compose version >/dev/null
docker info >/dev/null
docker build -t novelvids-updater:local -f scripts/update/Dockerfile .
docker run --rm --entrypoint python3 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$root:$root" -w "$root" \
  novelvids-updater:local /updater/install_docker.py "$root"
