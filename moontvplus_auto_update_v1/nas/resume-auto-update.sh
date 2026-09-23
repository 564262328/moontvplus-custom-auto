#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$ROOT/config.env"

rm -f "$STATE_DIR/PAUSED"
python3 "$ROOT/set-compose-image.py" "$COMPOSE_FILE" "$SERVICE" "$IMAGE"
echo "Automatic updates resumed. Running one update check now..."
exec "$ROOT/update-moontv.sh"
