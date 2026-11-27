#!/bin/sh
# Isolated MoonTVPlus V2.1 preview: never touches production containers or Kvrocks.
set -eu
umask 077

IMAGE="${1:-}"
case "$IMAGE" in
  ghcr.io/564262328/moontvplus-custom:preview-v21-pr5-*) ;;
  *) echo "ERROR: supply the immutable V2.1 PR #5 preview tag, never stable." >&2; exit 2 ;;
esac

ROOT=/vol2/1000/Docker/moontvplus-v21-preview
NAME=moontv-v21-preview
PORT=18081
PRODUCTION=moontv-core

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not found" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found" >&2; exit 2; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl needed for random preview password" >&2; exit 2; }

if ! docker inspect "$PRODUCTION" >/dev/null 2>&1; then
  echo "ERROR: expected production container not found. Refusing to guess deployment layout." >&2
  exit 3
fi
if docker inspect "$NAME" >/dev/null 2>&1; then
  echo "ERROR: $NAME already exists. Leaving it unchanged." >&2
  exit 4
fi
if [ -e "$ROOT/preview.env" ] || [ -e "$ROOT/data" ]; then
  echo "ERROR: existing preview state found at $ROOT; refusing to overwrite." >&2
  exit 5
fi

mkdir -p "$ROOT/data"
PASS="$(openssl rand -hex 20)"
cat > "$ROOT/preview.env" <<EOF
USERNAME=preview
PASSWORD=$PASS
NEXT_PUBLIC_STORAGE_TYPE=d1
SQLITE_DB_PATH=/app/.data/moontv-v21.db
DOCKER_ENV=true
EOF
chmod 600 "$ROOT/preview.env"
echo "Pulling isolated V2.1 image (production unchanged)..."
if ! docker pull "$IMAGE"; then
  echo "ERROR: preview image pull failed; no production change." >&2
  exit 6
fi

if ! docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --security-opt no-new-privileges \
  -p "$PORT:3000" \
  --env-file "$ROOT/preview.env" \
  -v "$ROOT/data:/app/.data" \
  "$IMAGE" >/dev/null; then
  echo "ERROR: preview container could not start. Production remains unchanged." >&2
  exit 7
fi

ok=0
i=0
while [ "$i" -lt 45 ]; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:$PORT/" 2>/dev/null || true)"
  case "$code" in
    200|301|302|307|308) ok=1; break ;;
  esac
  i=$((i+1))
  sleep 2
done
if [ "$ok" != 1 ]; then
  echo "ERROR: preview did not pass HTTP check, removing only $NAME." >&2
  docker logs --tail=80 "$NAME" >&2 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit 8
fi

echo "V2.1 PREVIEW PASS (HTTP $code)"
echo "Open in LAN: http://KING_NAS_IP:$PORT/"
echo "Preview login: preview"
echo "Preview password saved (root-only): $ROOT/preview.env"
echo "Production: $PRODUCTION (not changed)"
echo "Stop preview only: docker stop $NAME"
echo "Remove preview only: docker rm -f $NAME"
