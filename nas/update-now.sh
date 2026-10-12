#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$ROOT/config.env"

mkdir -p "$LOG_DIR" "$STATE_DIR"

if [ -d "$STATE_DIR/update.lock" ]; then
  echo "An update is already running."
  if [ -f "$STATE_DIR/update.lock/pid" ]; then
    echo "PID: $(cat "$STATE_DIR/update.lock/pid" 2>/dev/null || true)"
  fi
  exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/manual-update-$TS.log"

nohup "$ROOT/update-moontv.sh" >> "$LOG" 2>&1 </dev/null &
PID=$!

echo "$PID" > "$STATE_DIR/last-manual-update-pid"
printf '%s\n' "$LOG" > "$STATE_DIR/last-manual-update-log"

echo "MoonTV update started in background."
echo "PID: $PID"
echo "Log: $LOG"
echo
echo "You may close SSH now. Check later with:"
echo "  $ROOT/status.sh"
echo "  tail -n 120 $LOG"
