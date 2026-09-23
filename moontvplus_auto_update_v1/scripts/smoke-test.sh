#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:?usage: smoke-test.sh IMAGE}"
NAME="moontv-custom-smoke-${GITHUB_RUN_ID:-local}-${RANDOM}"
PORT="${SMOKE_PORT:-18083}"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d \
  --name "$NAME" \
  -p "127.0.0.1:${PORT}:3000" \
  -e USERNAME=smoke \
  -e PASSWORD=smoke \
  -e NEXT_PUBLIC_STORAGE_TYPE=d1 \
  -e SQLITE_DB_PATH=/app/.data/smoke.db \
  "$IMAGE" >/dev/null

ok=0
for _ in $(seq 1 45); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/" || true)"
  case "$code" in
    200|301|302|307|308)
      ok=1
      echo "Smoke HTTP=${code}"
      break
      ;;
  esac
  sleep 2
done

if [[ "$ok" != "1" ]]; then
  echo "ERROR: smoke test failed." >&2
  docker logs --tail=200 "$NAME" >&2 || true
  exit 30
fi

docker logs --tail=60 "$NAME" || true
echo "Smoke test passed."
