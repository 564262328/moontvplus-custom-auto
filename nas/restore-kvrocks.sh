#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONFIG="$ROOT/config.env"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: missing $CONFIG" >&2
  exit 2
fi

. "$CONFIG"

KVROCKS_CONTAINER="${KVROCKS_CONTAINER:-moontv-kvrocks}"
KVROCKS_PORT="${KVROCKS_PORT:-6666}"

refresh_dbsize() {
  C="$1"
  PREV="$(docker exec "$C" sh -lc "redis-cli -p $KVROCKS_PORT INFO keyspace" 2>/dev/null | tr -d '\r' | sed -n 's/^last_dbsize_scan_timestamp://p' | tail -1)"
  PREV="${PREV:-0}"
  NOW="$(date +%s)"

  if [ "$PREV" -ge "$NOW" ] 2>/dev/null; then
    sleep 1
  fi

  OUT="$(docker exec "$C" sh -lc "redis-cli -p $KVROCKS_PORT DBSIZE SCAN" 2>&1 | tr -d '\r')"
  if [ "$OUT" != "OK" ]; then
    echo "ERROR: DBSIZE SCAN was not accepted for $C: $OUT" >&2
    return 1
  fi

  elapsed=0
  while [ "$elapsed" -lt 120 ]; do
    TS="$(docker exec "$C" sh -lc "redis-cli -p $KVROCKS_PORT INFO keyspace" 2>/dev/null | tr -d '\r' | sed -n 's/^last_dbsize_scan_timestamp://p' | tail -1)"
    TS="${TS:-0}"

    if [ "$TS" -gt "$PREV" ] 2>/dev/null; then
      docker exec "$C" sh -lc "redis-cli -p $KVROCKS_PORT DBSIZE" | tr -d '\r'
      return 0
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "ERROR: DBSIZE SCAN timed out for $C" >&2
  return 1
}

BACKUP_PATH="${1:-}"
CONFIRM="${2:-}"

if [ -z "$BACKUP_PATH" ]; then
  echo "ERROR: backup path required" >&2
  exit 3
fi

if [ "$CONFIRM" != "--confirm-production-restore" ]; then
  echo "ERROR: refusing production restore without --confirm-production-restore" >&2
  exit 4
fi

ARCHIVE="$BACKUP_PATH/kvrocks-backup.tar.gz"
SUMS="$BACKUP_PATH/SHA256SUMS"

if [ ! -f "$ARCHIVE" ] || [ ! -f "$SUMS" ]; then
  echo "ERROR: incomplete backup: $BACKUP_PATH" >&2
  exit 5
fi

(cd "$BACKUP_PATH" && sha256sum -c SHA256SUMS)

if ! tar -tzf "$ARCHIVE" | grep -Eq '(^|/)CURRENT$'; then
  echo "ERROR: archive does not contain CURRENT" >&2
  exit 6
fi

IMAGE_REF="$(docker inspect "$KVROCKS_CONTAINER" --format '{{.Config.Image}}')"
KV_UID="$(docker exec "$KVROCKS_CONTAINER" sh -lc 'id -u kvrocks 2>/dev/null || echo 0')"
KV_GID="$(docker exec "$KVROCKS_CONTAINER" sh -lc 'id -g kvrocks 2>/dev/null || echo 0')"

echo "Stopping MoonTV core before database restore..."
docker stop "$CONTAINER" >/dev/null 2>&1 || true

echo "Stopping production Kvrocks..."
docker stop "$KVROCKS_CONTAINER" >/dev/null

echo "Restoring Kvrocks checkpoint from:"
echo "$BACKUP_PATH"

cat "$ARCHIVE" | docker run --rm -i   --user 0:0   --volumes-from "$KVROCKS_CONTAINER"   --entrypoint sh   "$IMAGE_REF"   -lc "set -eu
       test -d /var/lib/kvrocks/db
       find /var/lib/kvrocks/db -mindepth 1 -maxdepth 1 -exec rm -rf {} +
       tar -xzf - -C /var/lib/kvrocks/db
       test -f /var/lib/kvrocks/db/CURRENT
       chown -R $KV_UID:$KV_GID /var/lib/kvrocks/db
       chmod 755 /var/lib/kvrocks/db"

echo "Starting production Kvrocks..."
docker start "$KVROCKS_CONTAINER" >/dev/null

ready=0
i=0
while [ "$i" -lt 60 ]; do
  if docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT PING" 2>/dev/null | grep -q '^PONG$'; then
    ready=1
    break
  fi
  sleep 2
  i=$((i + 1))
done

if [ "$ready" != "1" ]; then
  echo "ERROR: production Kvrocks did not become ready after restore" >&2
  docker logs --tail=120 "$KVROCKS_CONTAINER" >&2 2>/dev/null || true
  exit 7
fi

echo "Refreshing restored exact key count..."
RESTORED_SIZE="$(refresh_dbsize "$KVROCKS_CONTAINER")"
echo "Restored production exact DBSIZE: $RESTORED_SIZE"

if [ -f "$BACKUP_PATH/dbsize.txt" ]; then
  EXPECTED_SIZE="$(tr -d '\r\n ' < "$BACKUP_PATH/dbsize.txt")"
  echo "Backup-time exact DBSIZE: $EXPECTED_SIZE"
  if [ -n "$EXPECTED_SIZE" ] && [ "$RESTORED_SIZE" != "$EXPECTED_SIZE" ]; then
    echo "ERROR: restored production exact DBSIZE does not match backup-time exact DBSIZE" >&2
    exit 8
  fi
fi

echo "KVROCKS PRODUCTION RESTORE OK"
echo "MoonTV core remains stopped; caller must recreate/start it after selecting the rollback image."
