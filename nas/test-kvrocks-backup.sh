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
STATE_DIR="${STATE_DIR:-$ROOT/state}"

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

if [ -z "$BACKUP_PATH" ]; then
  if [ ! -f "$STATE_DIR/last-kvrocks-backup" ]; then
    echo "ERROR: no backup path supplied and no last backup recorded" >&2
    exit 3
  fi
  BACKUP_PATH="$(cat "$STATE_DIR/last-kvrocks-backup")"
fi

ARCHIVE="$BACKUP_PATH/kvrocks-backup.tar.gz"
SUMS="$BACKUP_PATH/SHA256SUMS"

if [ ! -f "$ARCHIVE" ]; then
  echo "ERROR: backup archive not found: $ARCHIVE" >&2
  exit 4
fi

if [ ! -f "$SUMS" ]; then
  echo "ERROR: checksum file not found: $SUMS" >&2
  exit 5
fi

(cd "$BACKUP_PATH" && sha256sum -c SHA256SUMS)

if ! tar -tzf "$ARCHIVE" | grep -Eq '(^|/)CURRENT$'; then
  echo "ERROR: archive does not contain CURRENT" >&2
  exit 6
fi

TS="$(date +%Y%m%d-%H%M%S)"
VOL="moontv-kvrocks-restore-test-$TS"
NAME="moontv-kvrocks-restore-test-$TS"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

IMAGE_REF="$(docker inspect "$KVROCKS_CONTAINER" --format '{{.Config.Image}}')"
KV_UID="$(docker exec "$KVROCKS_CONTAINER" sh -lc 'id -u kvrocks 2>/dev/null || echo 0')"
KV_GID="$(docker exec "$KVROCKS_CONTAINER" sh -lc 'id -g kvrocks 2>/dev/null || echo 0')"

echo "Testing backup: $BACKUP_PATH"
echo "Temporary volume: $VOL"

docker volume create "$VOL" >/dev/null

cat "$ARCHIVE" | docker run --rm -i   --user 0:0   -v "$VOL:/restore-db"   --entrypoint sh   "$IMAGE_REF"   -lc "set -eu
       tar -xzf - -C /restore-db
       test -f /restore-db/CURRENT
       chown -R $KV_UID:$KV_GID /restore-db
       chmod 755 /restore-db"

docker run -d   --name "$NAME"   -v "$VOL:/var/lib/kvrocks/db"   "$IMAGE_REF" >/dev/null

ready=0
i=0
while [ "$i" -lt 60 ]; do
  if docker exec "$NAME" sh -lc "redis-cli -p $KVROCKS_PORT PING" 2>/dev/null | grep -q '^PONG$'; then
    ready=1
    break
  fi
  sleep 2
  i=$((i + 1))
done

if [ "$ready" != "1" ]; then
  echo "ERROR: temporary Kvrocks did not become ready" >&2
  docker logs --tail=120 "$NAME" >&2 2>/dev/null || true
  exit 7
fi

echo "Refreshing exact key counts with DBSIZE SCAN..."
PROD_SIZE="$(refresh_dbsize "$KVROCKS_CONTAINER")"
TEST_SIZE="$(refresh_dbsize "$NAME")"

echo "Production exact DBSIZE: $PROD_SIZE"
echo "Restored   exact DBSIZE: $TEST_SIZE"

if [ -f "$BACKUP_PATH/dbsize.txt" ]; then
  EXPECTED_SIZE="$(tr -d '\r\n ' < "$BACKUP_PATH/dbsize.txt")"
  echo "Backup-time exact DBSIZE: $EXPECTED_SIZE"
  if [ -n "$EXPECTED_SIZE" ] && [ "$TEST_SIZE" != "$EXPECTED_SIZE" ]; then
    echo "ERROR: restored exact DBSIZE does not match backup-time exact DBSIZE" >&2
    exit 8
  fi
fi

echo "KVROCKS RESTORE TEST OK"
