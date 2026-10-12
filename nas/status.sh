#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$ROOT/config.env"

KVROCKS_CONTAINER="${KVROCKS_CONTAINER:-moontv-kvrocks}"
KVROCKS_PORT="${KVROCKS_PORT:-6666}"
KVROCKS_AUTO_RESTORE="${KVROCKS_AUTO_RESTORE:-0}"
SKOPEO_IMAGE="${SKOPEO_IMAGE:-quay.io/skopeo/stable:latest}"
SKOPEO_RETRY_TIMES="${SKOPEO_RETRY_TIMES:-10}"
SKOPEO_PARALLEL_COPIES="${SKOPEO_PARALLEL_COPIES:-1}"
PULL_STRATEGY="${PULL_STRATEGY:-skopeo-first}"

echo "===== MoonTV custom update status ====="

if [ -f "$STATE_DIR/PAUSED" ]; then
  echo "UPDATE STATE: PAUSED"
  cat "$STATE_DIR/PAUSED"
else
  echo "UPDATE STATE: NOT PAUSED"
fi

if [ -d "$STATE_DIR/update.lock" ]; then
  echo "UPDATE PROCESS: RUNNING"
  if [ -f "$STATE_DIR/update.lock/pid" ]; then
    echo "UPDATE PID: $(cat "$STATE_DIR/update.lock/pid" 2>/dev/null || true)"
  fi
else
  echo "UPDATE PROCESS: IDLE"
fi

MARKER="# moontv-custom-auto-update"
if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q "$MARKER"; then
  echo "SCHEDULE: ENABLED"
else
  echo "SCHEDULE: NOT ENABLED"
fi

echo
echo "Pull strategy: $PULL_STRATEGY"
echo "Skopeo: $SKOPEO_IMAGE, retries=$SKOPEO_RETRY_TIMES, parallel=$SKOPEO_PARALLEL_COPIES"
if [ "$KVROCKS_AUTO_RESTORE" = "1" ]; then
  echo "Kvrocks automatic production restore: ENABLED"
else
  echo "Kvrocks automatic production restore: DISABLED (safe default)"
fi

echo
echo "Last remote check:"
cat "$STATE_DIR/last-remote-check" 2>/dev/null || echo "none"
echo "Last successful update:"
cat "$STATE_DIR/last-success" 2>/dev/null || echo "none"
echo "Last known good remote digest:"
cat "$STATE_DIR/current-good-remote-digest" 2>/dev/null || echo "none"

echo
docker ps --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

echo
echo "Container image ID:"
docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true
echo "Container image ref:"
docker inspect "$CONTAINER" --format '{{.Config.Image}}' 2>/dev/null || true
echo "Container version:"
docker inspect "$CONTAINER" --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true

echo
echo "Kvrocks:"
docker ps --filter "name=^/${KVROCKS_CONTAINER}$" --format 'table {{.Names}}\t{{.Status}}'
docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT PING" 2>/dev/null || true

echo
echo "Latest exported Kvrocks backup:"
if [ -f "$STATE_DIR/last-kvrocks-backup" ]; then
  LAST="$(cat "$STATE_DIR/last-kvrocks-backup")"
  echo "$LAST"
  du -sh "$LAST" 2>/dev/null || true
else
  echo "none"
fi

echo
curl -sS -o /dev/null -w 'HTTP=%{http_code}\n' --max-time 10 "$HTTP_URL" || true

if [ -f "$STATE_DIR/last-manual-update-log" ]; then
  echo
  echo "Latest manual background log:"
  cat "$STATE_DIR/last-manual-update-log" 2>/dev/null || true
fi
