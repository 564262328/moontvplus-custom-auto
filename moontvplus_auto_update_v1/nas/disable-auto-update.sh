#!/bin/sh
set -eu
MARKER="# moontv-custom-auto-update"
if command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v "$MARKER" || true) | crontab -
fi
echo "Automatic cron update disabled."
