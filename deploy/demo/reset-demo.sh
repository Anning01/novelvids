#!/bin/sh
set -eu

DEMO_ROOT=/srv/novelvids-demo
COMPOSE_FILE="$DEMO_ROOT/docker-compose.yml"
NEXT_RUNTIME="$DEMO_ROOT/.reset-next"
PREVIOUS_RUNTIME="$DEMO_ROOT/previous"

if [ "$DEMO_ROOT" != "/srv/novelvids-demo" ] || [ ! -f "$COMPOSE_FILE" ]; then
    echo "demo reset refused: unexpected deployment root" >&2
    exit 1
fi

exec 9>"$DEMO_ROOT/reset.lock"
flock -n 9 || exit 0

rm -rf "$NEXT_RUNTIME"
mkdir -p "$NEXT_RUNTIME/data" "$NEXT_RUNTIME/media"
cp "$DEMO_ROOT/golden/novelvids.db" "$NEXT_RUNTIME/data/novelvids.db"
cp -a "$DEMO_ROOT/golden/media/." "$NEXT_RUNTIME/media/"
chown -R 10001:10001 "$NEXT_RUNTIME"
chmod 0750 "$NEXT_RUNTIME" "$NEXT_RUNTIME/data" "$NEXT_RUNTIME/media"
chmod 0600 "$NEXT_RUNTIME/data/novelvids.db"

cd "$DEMO_ROOT"
docker compose -f "$COMPOSE_FILE" stop frontend backend
rm -rf "$PREVIOUS_RUNTIME"
if [ -d "$DEMO_ROOT/runtime" ]; then
    mv "$DEMO_ROOT/runtime" "$PREVIOUS_RUNTIME"
fi
mv "$NEXT_RUNTIME" "$DEMO_ROOT/runtime"

if docker compose -f "$COMPOSE_FILE" up -d --wait; then
    exit 0
fi

docker compose -f "$COMPOSE_FILE" stop frontend backend || true
rm -rf "$DEMO_ROOT/runtime"
if [ -d "$PREVIOUS_RUNTIME" ]; then
    mv "$PREVIOUS_RUNTIME" "$DEMO_ROOT/runtime"
    docker compose -f "$COMPOSE_FILE" up -d --wait
fi
exit 1
