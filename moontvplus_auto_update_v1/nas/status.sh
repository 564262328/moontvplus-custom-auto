#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$ROOT/config.env"

echo "===== MoonTV custom update status ====="
if [ -f "$STATE_DIR/PAUSED" ]; then
  echo "AUTO UPDATE: PAUSED"
  cat "$STATE_DIR/PAUSED"
else
  echo "AUTO UPDATE: enabled/not paused"
fi
echo
docker ps --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
echo
echo "Container image ID:"
docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true
echo "Container image ref:"
docker inspect "$CONTAINER" --format '{{.Config.Image}}' 2>/dev/null || true
echo
echo "Kvrocks:"
docker ps --filter name='^/moontv-kvrocks$' --format 'table {{.Names}}\t{{.Status}}'
echo
curl -sS -o /dev/null -w 'HTTP=%{http_code}\n' --max-time 10 "$HTTP_URL" || true
