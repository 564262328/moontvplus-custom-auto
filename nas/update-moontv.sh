#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONFIG="$ROOT/config.env"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: missing $CONFIG" >&2
  exit 2
fi

. "$CONFIG"

KVROCKS_BACKUP_ROOT="${KVROCKS_BACKUP_ROOT:-$ROOT/kvrocks-backups}"

mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$LOG_DIR" "$KVROCKS_BACKUP_ROOT"

PAUSE_FILE="$STATE_DIR/PAUSED"
LOCK_DIR="$STATE_DIR/update.lock"

if [ -f "$PAUSE_FILE" ]; then
  echo "Automatic updates are PAUSED:"
  cat "$PAUSE_FILE" 2>/dev/null || true
  exit 0
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another update process appears to be running."
  exit 0
fi

trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

TS="$(date +%Y%m%d-%H%M%S)"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container not found: $CONTAINER" >&2
  exit 3
fi

CURRENT_ID="$(docker inspect "$CONTAINER" --format '{{.Image}}')"
CURRENT_REF="$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')"

echo "Current container image ref: $CURRENT_REF"
echo "Current container image id : $CURRENT_ID"
echo "Target stable image        : $IMAGE"

echo "Pulling tested stable image..."
docker pull "$IMAGE"

NEW_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "Pulled stable image id      : $NEW_ID"

if [ "$CURRENT_ID" = "$NEW_ID" ]; then
  echo "Already up to date."
  exit 0
fi

echo
echo "===== Pre-update Kvrocks backup ====="
if ! sh "$ROOT/backup-kvrocks.sh"; then
  echo "ERROR: Kvrocks backup failed; MoonTV update aborted before any production change." >&2
  exit 11
fi

KV_BACKUP="$(cat "$STATE_DIR/last-kvrocks-backup")"
printf '%s\n' "$KV_BACKUP" > "$STATE_DIR/pre-update-kvrocks-backup"
echo "Protected Kvrocks checkpoint: $KV_BACKUP"

ROLLBACK_TAG="moontvplus-custom:rollback-$TS"
docker tag "$CURRENT_ID" "$ROLLBACK_TAG"

BACKUP="$BACKUP_DIR/docker-compose-$TS.yml"
cp -a "$COMPOSE_FILE" "$BACKUP"

echo "$ROLLBACK_TAG" > "$STATE_DIR/previous-image"
echo "$BACKUP" > "$STATE_DIR/previous-compose-backup"

python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$IMAGE"

cd "$LUNA_DIR"
if ! docker compose -f "$COMPOSE_FILE" config >/dev/null; then
  echo "ERROR: compose validation failed; restoring previous compose." >&2
  cp -a "$BACKUP" "$COMPOSE_FILE"
  exit 12
fi

echo "Recreating ONLY $SERVICE. Kvrocks will not be restarted."
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE"

healthy=0
i=1
while [ "$i" -le "$HEALTH_ATTEMPTS" ]; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$HTTP_URL" 2>/dev/null || true)"
  running="$(docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null || echo false)"

  case "$code" in
    200|301|302|307|308)
      if [ "$running" = "true" ]; then
        healthy=1
        break
      fi
      ;;
  esac

  sleep "$HEALTH_SLEEP_SECONDS"
  i=$((i + 1))
done

if [ "$healthy" = "1" ]; then
  echo "$NEW_ID" > "$STATE_DIR/current-good-image-id"
  date '+%Y-%m-%d %H:%M:%S %z' > "$STATE_DIR/last-success"
  rm -f "$STATE_DIR/last-failure"
  echo "UPDATE SUCCESS: HTTP=$code"
  echo "Kvrocks pre-update checkpoint retained at: $KV_BACKUP"
  exit 0
fi

echo "UPDATE FAILED. Rolling application image back to $ROLLBACK_TAG ..." >&2
docker logs --tail=120 "$CONTAINER" >&2 2>/dev/null || true

python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$ROLLBACK_TAG"
cd "$LUNA_DIR"
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE" || true

{
  echo "Paused after failed update at $(date '+%Y-%m-%d %H:%M:%S %z')."
  echo "Failed target: $IMAGE"
  echo "Application rolled back to: $ROLLBACK_TAG"
  echo "Pre-update Kvrocks backup: $KV_BACKUP"
  echo "Kvrocks was NOT automatically restored."
  echo "Run test-kvrocks-backup.sh against that backup before any manual DB restore."
} > "$PAUSE_FILE"

cp -a "$PAUSE_FILE" "$STATE_DIR/last-failure"

echo "Application rollback attempted. Automatic updates are PAUSED for safety." >&2
echo "Kvrocks recovery checkpoint: $KV_BACKUP" >&2
exit 20
