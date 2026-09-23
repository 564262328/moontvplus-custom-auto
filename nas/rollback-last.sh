#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$ROOT/config.env"

PREV="$STATE_DIR/previous-image"
if [ ! -f "$PREV" ]; then
  echo "No previous image recorded." >&2
  exit 2
fi

IMAGE_REF="$(cat "$PREV")"
if ! docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
  echo "Previous rollback image no longer exists locally: $IMAGE_REF" >&2
  exit 3
fi

python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$IMAGE_REF"
cd "$LUNA_DIR"
docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE"

{
  echo "Paused after manual rollback at $(date '+%Y-%m-%d %H:%M:%S %z')."
  echo "Current compose image: $IMAGE_REF"
} > "$STATE_DIR/PAUSED"

echo "Rolled back to: $IMAGE_REF"
echo "Automatic updates are PAUSED."
