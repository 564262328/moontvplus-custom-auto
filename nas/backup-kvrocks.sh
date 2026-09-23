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
KVROCKS_BACKUP_ROOT="${KVROCKS_BACKUP_ROOT:-$ROOT/kvrocks-backups}"
KVROCKS_BACKUP_KEEP="${KVROCKS_BACKUP_KEEP:-7}"
KVROCKS_BGSAVE_TIMEOUT_SECONDS="${KVROCKS_BGSAVE_TIMEOUT_SECONDS:-300}"

mkdir -p "$STATE_DIR" "$KVROCKS_BACKUP_ROOT"

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

if ! docker inspect "$KVROCKS_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: Kvrocks container not found: $KVROCKS_CONTAINER" >&2
  exit 3
fi

if ! docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT PING" 2>/dev/null | grep -q '^PONG$'; then
  echo "ERROR: Kvrocks PING failed" >&2
  exit 4
fi

echo "Refreshing exact Kvrocks key count..."
EXACT_DBSIZE="$(refresh_dbsize "$KVROCKS_CONTAINER")"
echo "Exact DBSIZE: $EXACT_DBSIZE"

BACKUP_SRC="$(docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT --raw CONFIG GET backup-dir | tail -1" | tr -d '\r')"
if [ -z "$BACKUP_SRC" ]; then
  echo "ERROR: unable to read Kvrocks backup-dir" >&2
  exit 5
fi

echo "Kvrocks backup-dir: $BACKUP_SRC"
echo "Triggering BGSAVE..."

BGSAVE_OUT="$(docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT BGSAVE" 2>&1 || true)"
echo "$BGSAVE_OUT"

elapsed=0
while :; do
  INFO="$(docker exec "$KVROCKS_CONTAINER" sh -lc "redis-cli -p $KVROCKS_PORT INFO persistence" | tr -d '\r')"
  INPROGRESS="$(printf '%s\n' "$INFO" | sed -n 's/^bgsave_in_progress://p' | tail -1)"
  STATUS="$(printf '%s\n' "$INFO" | sed -n 's/^last_bgsave_status://p' | tail -1)"

  echo "bgsave_in_progress=${INPROGRESS:-unknown} last_bgsave_status=${STATUS:-unknown}"

  if [ "${INPROGRESS:-1}" = "0" ]; then
    if [ "${STATUS:-err}" = "ok" ]; then
      break
    fi
    echo "ERROR: Kvrocks BGSAVE finished with status: ${STATUS:-unknown}" >&2
    exit 6
  fi

  if [ "$elapsed" -ge "$KVROCKS_BGSAVE_TIMEOUT_SECONDS" ]; then
    echo "ERROR: Kvrocks BGSAVE timed out after ${KVROCKS_BGSAVE_TIMEOUT_SECONDS}s" >&2
    exit 7
  fi

  sleep 2
  elapsed=$((elapsed + 2))
done

if ! docker exec "$KVROCKS_CONTAINER" sh -lc "test -f '$BACKUP_SRC/CURRENT'"; then
  echo "ERROR: backup does not contain CURRENT" >&2
  exit 8
fi

TS="$(date +%Y%m%d-%H%M%S)"
DEST="$KVROCKS_BACKUP_ROOT/$TS"
mkdir -p "$DEST"

echo "Exporting checkpoint to: $DEST"
docker exec "$KVROCKS_CONTAINER" sh -lc "tar -C '$BACKUP_SRC' -czf - ." > "$DEST/kvrocks-backup.tar.gz"

if [ ! -s "$DEST/kvrocks-backup.tar.gz" ]; then
  echo "ERROR: exported archive is empty" >&2
  rm -rf "$DEST"
  exit 9
fi

if ! tar -tzf "$DEST/kvrocks-backup.tar.gz" | grep -Eq '(^|/)CURRENT$'; then
  echo "ERROR: exported archive does not contain CURRENT" >&2
  rm -rf "$DEST"
  exit 10
fi

printf '%s\n' "$EXACT_DBSIZE" > "$DEST/dbsize.txt"
docker inspect "$KVROCKS_CONTAINER" --format '{{.Config.Image}}' > "$DEST/kvrocks-image-ref.txt"
docker inspect "$KVROCKS_CONTAINER" --format '{{.Image}}' > "$DEST/kvrocks-image-id.txt"
date '+%Y-%m-%d %H:%M:%S %z' > "$DEST/created-at.txt"
printf '%s\n' "$BACKUP_SRC" > "$DEST/source-backup-dir.txt"
(cd "$DEST" && sha256sum kvrocks-backup.tar.gz > SHA256SUMS)

printf '%s\n' "$DEST" > "$STATE_DIR/last-kvrocks-backup"

KEEP="$KVROCKS_BACKUP_KEEP"
if [ "$KEEP" -gt 0 ] 2>/dev/null; then
  n=0
  for d in $(ls -1dt "$KVROCKS_BACKUP_ROOT"/* 2>/dev/null || true); do
    n=$((n + 1))
    if [ "$n" -gt "$KEEP" ]; then
      rm -rf "$d"
    fi
  done
fi

echo "KVROCKS BACKUP OK"
echo "Backup: $DEST"
echo "Recorded exact DBSIZE: $EXACT_DBSIZE"
du -sh "$DEST" 2>/dev/null || true
