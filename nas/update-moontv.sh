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
KVROCKS_AUTO_RESTORE="${KVROCKS_AUTO_RESTORE:-0}"

SKOPEO_IMAGE="${SKOPEO_IMAGE:-quay.io/skopeo/stable:latest}"
SKOPEO_RETRY_TIMES="${SKOPEO_RETRY_TIMES:-10}"
SKOPEO_RETRY_DELAY="${SKOPEO_RETRY_DELAY:-10s}"
SKOPEO_PARALLEL_COPIES="${SKOPEO_PARALLEL_COPIES:-1}"
PULL_STRATEGY="${PULL_STRATEGY:-skopeo-first}"
REMOTE_CHECK_RETRIES="${REMOTE_CHECK_RETRIES:-3}"
REMOTE_CHECK_DELAY_SECONDS="${REMOTE_CHECK_DELAY_SECONDS:-10}"
REMOTE_INSPECT_TIMEOUT_SECONDS="${REMOTE_INSPECT_TIMEOUT_SECONDS:-45}"
SKOPEO_PULL_TIMEOUT_SECONDS="${SKOPEO_PULL_TIMEOUT_SECONDS:-1200}"
SKOPEO_PROXY_PULL_TIMEOUT_SECONDS="${SKOPEO_PROXY_PULL_TIMEOUT_SECONDS:-$SKOPEO_PULL_TIMEOUT_SECONDS}"
SKOPEO_DIRECT_PULL_TIMEOUT_SECONDS="${SKOPEO_DIRECT_PULL_TIMEOUT_SECONDS:-600}"
DOCKER_PULL_TIMEOUT_SECONDS="${DOCKER_PULL_TIMEOUT_SECONDS:-600}"

REGISTRY_PROXY_MODE="${REGISTRY_PROXY_MODE:-prefer}"
REGISTRY_PROXY_URL="${REGISTRY_PROXY_URL:-http://127.0.0.1:7890}"
REGISTRY_PROXY_PROBE_URL="${REGISTRY_PROXY_PROBE_URL:-https://ghcr.io/v2/}"
REGISTRY_PROXY_PROBE_TIMEOUT_SECONDS="${REGISTRY_PROXY_PROBE_TIMEOUT_SECONDS:-8}"

mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$LOG_DIR" "$KVROCKS_BACKUP_ROOT"

PAUSE_FILE="$STATE_DIR/PAUSED"
LOCK_DIR="$STATE_DIR/update.lock"
LAST_GOOD_REMOTE_DIGEST="$STATE_DIR/current-good-remote-digest"
LAST_REMOTE_CHECK="$STATE_DIR/last-remote-check"
LAST_REMOTE_DIGEST="$STATE_DIR/last-remote-digest"

if [ -f "$PAUSE_FILE" ]; then
  echo "Automatic updates are PAUSED:"
  cat "$PAUSE_FILE" 2>/dev/null || true
  exit 0
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another update process appears to be running."
  exit 0
fi

echo "$$" > "$LOCK_DIR/pid"
trap 'rm -f "$LOCK_DIR/pid" 2>/dev/null || true; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

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
    echo "Rollback image: ${ROLLBACK_TAG:-not-created}"
    echo "Pre-update Kvrocks backup: ${KV_BACKUP:-not-created}"
    echo "$1"
  } > "$PAUSE_FILE"

  cp -a "$PAUSE_FILE" "$STATE_DIR/last-failure"
}

ensure_skopeo() {
  if docker image inspect "$SKOPEO_IMAGE" >/dev/null 2>&1; then
    return 0
  fi

  echo "Skopeo helper image is not local; pulling it once..."
  if run_with_timeout "$DOCKER_PULL_TIMEOUT_SECONDS" docker pull "$SKOPEO_IMAGE"; then
    return 0
  fi

  echo "ERROR: could not obtain Skopeo helper image." >&2
  return 1
}

run_with_timeout() {
  limit="$1"
  shift

  if command -v timeout >/dev/null 2>&1; then
    timeout "$limit" "$@"
    return $?
  fi

  "$@" &
  child=$!
  started="$(date +%s)"

  while kill -0 "$child" 2>/dev/null; do
    now="$(date +%s)"
    if [ $((now - started)) -ge "$limit" ]; then
      echo "WARNING: command exceeded timeout of ${limit}s; terminating it." >&2
      kill -TERM "$child" 2>/dev/null || true
      sleep 3
      kill -KILL "$child" 2>/dev/null || true
      wait "$child" 2>/dev/null || true
      return 124
    fi
    sleep 5
  done

  wait "$child"
}

proxy_available() {
  [ -n "$REGISTRY_PROXY_URL" ] || return 1

  case "$REGISTRY_PROXY_MODE" in
    off)
      return 1
      ;;
    prefer|force)
      ;;
    *)
      echo "ERROR: unsupported REGISTRY_PROXY_MODE=$REGISTRY_PROXY_MODE (use off, prefer, or force)." >&2
      return 2
      ;;
  esac

  curl -x "$REGISTRY_PROXY_URL"     -sS -o /dev/null     --max-time "$REGISTRY_PROXY_PROBE_TIMEOUT_SECONDS"     "$REGISTRY_PROXY_PROBE_URL" >/dev/null 2>&1
}

run_skopeo_inspect() {
  mode="$1"

  if [ "$mode" = "proxy" ]; then
    run_with_timeout "$REMOTE_INSPECT_TIMEOUT_SECONDS"       docker run --rm         --network host         -e HTTP_PROXY="$REGISTRY_PROXY_URL"         -e HTTPS_PROXY="$REGISTRY_PROXY_URL"         -e ALL_PROXY="$REGISTRY_PROXY_URL"         -e NO_PROXY='localhost,127.0.0.1,::1'         "$SKOPEO_IMAGE"         inspect "docker://$IMAGE"
  else
    run_with_timeout "$REMOTE_INSPECT_TIMEOUT_SECONDS"       docker run --rm         --network host         -e HTTP_PROXY= -e HTTPS_PROXY= -e ALL_PROXY=         -e http_proxy= -e https_proxy= -e all_proxy=         "$SKOPEO_IMAGE"         inspect "docker://$IMAGE"
  fi
}

inspect_remote_once() {
  mode="$1"

  if REMOTE_JSON="$(run_skopeo_inspect "$mode" 2>/dev/null)"; then
    REMOTE_DIGEST="$(printf '%s' "$REMOTE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Digest") or "")')"
    REMOTE_VERSION="$(printf '%s' "$REMOTE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); l=d.get("Labels") or {}; print(l.get("org.opencontainers.image.version") or "")')"
    REMOTE_REVISION="$(printf '%s' "$REMOTE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); l=d.get("Labels") or {}; print(l.get("org.opencontainers.image.revision") or "")')"
    REMOTE_UI="$(printf '%s' "$REMOTE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); l=d.get("Labels") or {}; print(l.get("io.moontvplus.custom.ui.version") or "")')"

    if [ -n "$REMOTE_DIGEST" ]; then
      printf '%s\n' "$mode" > "$STATE_DIR/last-registry-transport"
      return 0
    fi
  fi

  return 1
}

fetch_remote_metadata() {
  ensure_skopeo || return 1

  attempt=1
  while [ "$attempt" -le "$REMOTE_CHECK_RETRIES" ]; do
    echo "Checking remote stable metadata (attempt $attempt/$REMOTE_CHECK_RETRIES)..."

    if [ "$REGISTRY_PROXY_MODE" != "force" ]; then
      echo "Trying direct registry metadata check first..."
      if inspect_remote_once direct; then
        printf '%s\n' "$REMOTE_DIGEST" > "$LAST_REMOTE_DIGEST"
        date '+%Y-%m-%d %H:%M:%S %z' > "$LAST_REMOTE_CHECK"
        echo "Registry metadata transport: direct"
        return 0
      fi
      echo "WARNING: direct metadata check failed." >&2
    fi

    if proxy_available; then
      echo "Trying proxy registry metadata check..."
      if inspect_remote_once proxy; then
        printf '%s\n' "$REMOTE_DIGEST" > "$LAST_REMOTE_DIGEST"
        date '+%Y-%m-%d %H:%M:%S %z' > "$LAST_REMOTE_CHECK"
        echo "Registry metadata transport: proxy"
        return 0
      fi
      echo "WARNING: proxy metadata check failed." >&2
    elif [ "$REGISTRY_PROXY_MODE" = "force" ]; then
      echo "WARNING: forced proxy unavailable." >&2
    fi

    if [ "$attempt" -lt "$REMOTE_CHECK_RETRIES" ]; then
      sleep "$REMOTE_CHECK_DELAY_SECONDS"
    fi
    attempt=$((attempt + 1))
  done

  echo "ERROR: remote stable metadata check failed. Production was not changed." >&2
  return 1
}

pull_with_skopeo_mode() {
  mode="$1"
  helper_name="moontv-skopeo-pull-$(date +%s)"

  if [ "$mode" = "proxy" ]; then
    pull_timeout="$SKOPEO_PROXY_PULL_TIMEOUT_SECONDS"
  else
    pull_timeout="$SKOPEO_DIRECT_PULL_TIMEOUT_SECONDS"
  fi

  echo
  echo "===== Skopeo resilient image pull ($mode) ====="
  echo "Helper image    : $SKOPEO_IMAGE"
  echo "Retry times     : $SKOPEO_RETRY_TIMES"
  echo "Retry delay     : $SKOPEO_RETRY_DELAY"
  echo "Parallel copies : $SKOPEO_PARALLEL_COPIES"
  echo "Hard timeout    : ${pull_timeout}s"

  cleanup_helper() {
    docker rm -f "$helper_name" >/dev/null 2>&1 || true
  }

  trap 'cleanup_helper; rm -f "$LOCK_DIR/pid" 2>/dev/null || true; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

  if [ "$mode" = "proxy" ]; then
    if run_with_timeout "$pull_timeout"       docker run --name "$helper_name" --rm         --network host         -e HTTP_PROXY="$REGISTRY_PROXY_URL"         -e HTTPS_PROXY="$REGISTRY_PROXY_URL"         -e ALL_PROXY="$REGISTRY_PROXY_URL"         -e NO_PROXY='localhost,127.0.0.1,::1'         -v /var/run/docker.sock:/var/run/docker.sock         "$SKOPEO_IMAGE"         copy         --retry-times "$SKOPEO_RETRY_TIMES"         --retry-delay "$SKOPEO_RETRY_DELAY"         --image-parallel-copies "$SKOPEO_PARALLEL_COPIES"         "docker://$IMAGE"         "docker-daemon:$IMAGE"; then
      rc=0
    else
      rc=$?
    fi
  else
    if run_with_timeout "$pull_timeout"       docker run --name "$helper_name" --rm         --network host         -e HTTP_PROXY= -e HTTPS_PROXY= -e ALL_PROXY=         -e http_proxy= -e https_proxy= -e all_proxy=         -v /var/run/docker.sock:/var/run/docker.sock         "$SKOPEO_IMAGE"         copy         --retry-times "$SKOPEO_RETRY_TIMES"         --retry-delay "$SKOPEO_RETRY_DELAY"         --image-parallel-copies "$SKOPEO_PARALLEL_COPIES"         "docker://$IMAGE"         "docker-daemon:$IMAGE"; then
      rc=0
    else
      rc=$?
    fi
  fi

  cleanup_helper
  trap 'rm -f "$LOCK_DIR/pid" 2>/dev/null || true; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

  if [ "$rc" -eq 124 ]; then
    echo "WARNING: Skopeo $mode pull watchdog fired after ${pull_timeout}s." >&2
  fi

  if [ "$rc" -eq 0 ]; then
    printf '%s\n' "skopeo-$mode" > "$STATE_DIR/last-registry-transport"
  fi

  return "$rc"
}

pull_with_skopeo() {
  ensure_skopeo || return 1

  if [ "$REGISTRY_PROXY_MODE" != "force" ]; then
    echo "Trying direct Skopeo pull first..."
    if pull_with_skopeo_mode direct; then
      return 0
    fi
    echo "WARNING: direct Skopeo pull failed." >&2
  fi

  if proxy_available; then
    echo "Trying proxied Skopeo pull..."
    if pull_with_skopeo_mode proxy; then
      return 0
    fi
    echo "WARNING: proxied Skopeo pull failed." >&2
  elif [ "$REGISTRY_PROXY_MODE" = "force" ]; then
    echo "ERROR: forced proxy unavailable." >&2
  fi

  return 1
}

pull_with_docker() {
  echo "Docker pull hard timeout: ${DOCKER_PULL_TIMEOUT_SECONDS}s"
  echo "NOTE: Docker daemon pull is a direct fallback and does not inherit the Skopeo proxy settings."

  if run_with_timeout "$DOCKER_PULL_TIMEOUT_SECONDS" docker pull "$IMAGE"; then
    printf '%s\n' "docker-direct" > "$STATE_DIR/last-registry-transport"
    return 0
  else
    rc=$?
  fi

  if [ "$rc" -eq 124 ]; then
    echo "WARNING: Docker pull watchdog fired after ${DOCKER_PULL_TIMEOUT_SECONDS}s." >&2
  fi
  return "$rc"
}

pull_target_image() {
  case "$PULL_STRATEGY" in
    skopeo)
      pull_with_skopeo
      ;;
    skopeo-first)
      if pull_with_skopeo; then
        echo "Skopeo pull succeeded."
        return 0
      fi
      echo "WARNING: Skopeo pull failed; trying normal Docker pull once." >&2
      pull_with_docker
      ;;
    docker-first)
      echo "Pulling tested stable image with Docker..."
      if pull_with_docker; then
        echo "Docker pull succeeded."
        return 0
      fi
      echo "WARNING: normal Docker pull failed; switching to Skopeo." >&2
      pull_with_skopeo
      ;;
    *)
      echo "ERROR: unsupported PULL_STRATEGY=$PULL_STRATEGY (use skopeo, skopeo-first, or docker-first)." >&2
      return 1
      ;;
  esac
}

TS="$(date +%Y%m%d-%H%M%S)"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container not found: $CONTAINER" >&2
  exit 3
fi

CURRENT_ID="$(docker inspect "$CONTAINER" --format '{{.Image}}')"
CURRENT_REF="$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')"
CURRENT_VERSION="$(docker inspect "$CONTAINER" --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true)"
CURRENT_REVISION="$(docker inspect "$CONTAINER" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)"
CURRENT_UI="$(docker inspect "$CONTAINER" --format '{{index .Config.Labels "io.moontvplus.custom.ui.version"}}' 2>/dev/null || true)"

echo "Current container image ref: $CURRENT_REF"
echo "Current container image id : $CURRENT_ID"
echo "Current version            : $CURRENT_VERSION"
echo "Current revision           : $CURRENT_REVISION"
echo "Target stable image        : $IMAGE"
echo "Pull strategy              : $PULL_STRATEGY"

if ! fetch_remote_metadata; then
  exit 10
fi

echo "Remote digest              : $REMOTE_DIGEST"
echo "Remote version             : $REMOTE_VERSION"
echo "Remote revision            : $REMOTE_REVISION"
echo "Remote UI                  : $REMOTE_UI"

if [ -f "$LAST_GOOD_REMOTE_DIGEST" ] && [ "$(cat "$LAST_GOOD_REMOTE_DIGEST" 2>/dev/null || true)" = "$REMOTE_DIGEST" ]; then
  echo "Remote stable digest is unchanged. Already up to date; no image download needed."
  exit 0
fi

# Synchronize digest state without a large pull whenever the running container
# already matches the exact remote upstream/UI metadata. This also covers a
# manual safe deployment where the digest marker still points at the prior tag.
if [ -n "$REMOTE_REVISION" ]   && [ "$CURRENT_REVISION" = "$REMOTE_REVISION" ]   && [ "$CURRENT_VERSION" = "$REMOTE_VERSION" ]   && [ "$CURRENT_UI" = "$REMOTE_UI" ]; then
  printf '%s\n' "$REMOTE_DIGEST" > "$LAST_GOOD_REMOTE_DIGEST"
  echo "Running container already matches remote stable metadata. Digest state synchronized; no download needed."
  exit 0
fi

echo
echo "New remote stable detected. Downloading in the background-safe updater process..."

if ! pull_target_image; then
  echo "ERROR: image download failed after all configured strategies. Production was not changed." >&2
  exit 10
fi

NEW_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "Available stable image id   : $NEW_ID"

if [ "$CURRENT_ID" = "$NEW_ID" ]; then
  printf '%s\n' "$REMOTE_DIGEST" > "$LAST_GOOD_REMOTE_DIGEST"
  echo "Local image already matches the running container. Digest state updated."
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

echo "Recreating ONLY $SERVICE from the already-downloaded image. Kvrocks will not be restarted."
docker compose -f "$COMPOSE_FILE" up -d   --no-deps   --force-recreate   --pull never   "$SERVICE"

if check_health; then
  echo "$NEW_ID" > "$STATE_DIR/current-good-image-id"
  printf '%s\n' "$REMOTE_DIGEST" > "$LAST_GOOD_REMOTE_DIGEST"
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
docker compose -f "$COMPOSE_FILE" up -d   --no-deps   --force-recreate   --pull never   "$SERVICE" || true

if check_health; then
  write_pause "Application rollback is healthy (HTTP=$code). Kvrocks was left untouched. Automatic updates remain paused for review."
  echo "Application rollback succeeded: HTTP=$code" >&2
  echo "Kvrocks was left untouched." >&2
  echo "Automatic updates are now PAUSED." >&2
  exit 20
fi

if [ "$KVROCKS_AUTO_RESTORE" != "1" ]; then
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  write_pause "Rollback image remained unhealthy. Automatic Kvrocks restore is disabled (KVROCKS_AUTO_RESTORE=$KVROCKS_AUTO_RESTORE). Production Kvrocks was NOT overwritten. MoonTV core was stopped for manual review."
  echo "CRITICAL: rollback image is also unhealthy." >&2
  echo "Production Kvrocks was NOT restored or modified." >&2
  echo "MoonTV core has been stopped and automatic updates are PAUSED." >&2
  echo "Manual recovery can use: $KV_BACKUP" >&2
  exit 21
fi

echo "WARNING: KVROCKS_AUTO_RESTORE=1. Validating the exact pre-update backup before production restore..." >&2

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
docker compose -f "$COMPOSE_FILE" up -d   --no-deps   --force-recreate   --pull never   "$SERVICE" || true

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
