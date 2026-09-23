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

check_health() {
  healthy=0
  code=000
  i=1

  while [ "$i" -le "$HEALTH_ATTEMPTS" ]; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$HTTP_URL" 2>/dev/null || true)"
    running="$(docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null || echo false)"

    case "$code" in
      200|301|302|307|308)
        if [ "$running" = "true" ]; then
          healthy=1
          return 0
        fi
        ;;
    esac

    sleep "$HEALTH_SLEEP_SECONDS"
    i=$((i + 1))
  done

  return 1
}

write_pause() {
  {
    echo "Paused after failed update at $(date '+%Y-%m-%d %H:%M:%S %z')."
    echo "Failed target: $IMAGE"
    echo "Rollback image: $ROLLBACK_TAG"
    echo "Pre-update Kvrocks backup: $KV_BACKUP"
    echo "$1"
  } > "$PAUSE_FILE"

  cp -a "$PAUSE_FILE" "$STATE_DIR/last-failure"
}

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
echo "===== Quiesce MoonTV before Kvrocks checkpoint ====="
echo "Stopping $CONTAINER briefly so backup metadata and checkpoint describe the same data state..."
docker stop "$CONTAINER" >/dev/null

echo
echo "===== Pre-update Kvrocks backup ====="
if ! sh "$ROOT/backup-kvrocks.sh"; then
  echo "ERROR: Kvrocks backup failed; restarting existing MoonTV without changing its image." >&2
  docker start "$CONTAINER" >/dev/null 2>&1 || true
  exit 11
fi

KV_BACKUP="$(cat "$STATE_DIR/last-kvrocks-backup")"
printf '%s\n' "$KV_BACKUP" > "$STATE_DIR/pre-update-kvrocks-backup"
echo "Protected Kvrocks checkpoint: $KV_BACKUP"

echo
echo "===== Validate checkpoint in isolated Kvrocks ====="
if ! sh "$ROOT/test-kvrocks-backup.sh" "$KV_BACKUP"; then
  echo "ERROR: isolated Kvrocks restore validation failed; restarting existing MoonTV and aborting update." >&2
  docker start "$CONTAINER" >/dev/null 2>&1 || true
  exit 13
fi

ROLLBACK_TAG="moontvplus-custom:rollback-$TS"
docker tag "$CURRENT_ID" "$ROLLBACK_TAG"

BACKUP="$BACKUP_DIR/docker-compose-$TS.yml"
cp -a "$COMPOSE_FILE" "$BACKUP"

echo "$ROLLBACK_TAG" > "$STATE_DIR/previous-image"
echo "$BACKUP" > "$STATE_DIR/previous-compose-backup"

python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$IMAGE"

cd "$LUNA_DIR"
if ! docker compose -f "$COMPOSE_FILE" config >/dev/null; then
  echo "ERROR: compose validation failed; restoring previous compose and restarting existing MoonTV." >&2
  cp -a "$BACKUP" "$COMPOSE_FILE"
  docker start "$CONTAINER" >/dev/null 2>&1 || true
  exit 12
fi

echo "Recreating ONLY $SERVICE. Kvrocks will not be restarted."
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE"

if check_health; then
  echo "$NEW_ID" > "$STATE_DIR/current-good-image-id"
  date '+%Y-%m-%d %H:%M:%S %z' > "$STATE_DIR/last-success"
  rm -f "$STATE_DIR/last-failure"
  echo "UPDATE SUCCESS: HTTP=$code"
  echo "Kvrocks pre-update checkpoint retained at: $KV_BACKUP"
  exit 0
fi

echo "UPDATE FAILED. Trying application-only rollback first..." >&2
docker logs --tail=120 "$CONTAINER" >&2 2>/dev/null || true

python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$ROLLBACK_TAG"
cd "$LUNA_DIR"
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE" || true

if check_health; then
  write_pause "Application rollback is healthy (HTTP=$code). Kvrocks was left untouched. Automatic updates remain paused for review."
  echo "Application rollback succeeded: HTTP=$code" >&2
  echo "Kvrocks was left untouched." >&2
  echo "Automatic updates are now PAUSED." >&2
  exit 20
fi

echo "Rollback image is also unhealthy. Validating pre-update Kvrocks backup..." >&2

if ! sh "$ROOT/test-kvrocks-backup.sh" "$KV_BACKUP"; then
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  write_pause "Rollback image remained unhealthy. Isolated Kvrocks restore validation FAILED. MoonTV core was stopped; production Kvrocks was not overwritten."
  echo "CRITICAL: isolated backup validation failed. Production Kvrocks was NOT restored." >&2
  exit 21
fi

echo "Backup validation passed. Restoring production Kvrocks to pre-update checkpoint..." >&2

if ! sh "$ROOT/restore-kvrocks.sh" "$KV_BACKUP" --confirm-production-restore; then
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  write_pause "Rollback image remained unhealthy. Production Kvrocks restore was attempted but FAILED. MoonTV core is stopped; manual intervention required."
  echo "CRITICAL: production Kvrocks restore failed. MoonTV core remains stopped." >&2
  exit 22
fi

cd "$LUNA_DIR"
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE" || true

if check_health; then
  write_pause "Full rollback succeeded: previous application image + pre-update Kvrocks checkpoint restored (HTTP=$code). Automatic updates remain paused for review."
  echo "FULL ROLLBACK SUCCESS: HTTP=$code" >&2
  echo "Previous application image and Kvrocks checkpoint were restored." >&2
  echo "Automatic updates are now PAUSED for review." >&2
  exit 20
fi

docker stop "$CONTAINER" >/dev/null 2>&1 || true
write_pause "Full rollback was attempted, but MoonTV is still unhealthy. MoonTV core was stopped; Kvrocks is running from the restored checkpoint. Manual intervention required."

echo "CRITICAL: full rollback completed but MoonTV health check still failed." >&2
echo "MoonTV core has been stopped. Kvrocks is running from the restored checkpoint." >&2
exit 23
