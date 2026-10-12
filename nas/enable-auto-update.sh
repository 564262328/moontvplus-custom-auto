#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MARKER="# moontv-custom-auto-update"
LINE="17 2 * * * $ROOT/update-moontv.sh >> $ROOT/logs/auto-update.log 2>&1 $MARKER"

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab command not found."
  echo "Create a daily task in the NAS task scheduler that runs:"
  echo "$ROOT/update-moontv.sh"
  exit 3
fi

(
  crontab -l 2>/dev/null | grep -v "$MARKER" || true
  echo "$LINE"
) | crontab -

echo "Automatic NAS update enabled:"
echo "$LINE"
echo
echo "The updater performs a lightweight remote digest check first. If stable is unchanged, it exits without downloading image layers."
