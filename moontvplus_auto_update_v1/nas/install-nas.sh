#!/bin/sh
set -eu

OWNER="${1:-}"
if [ -z "$OWNER" ]; then
  echo "usage: ./install-nas.sh GITHUB_USERNAME_OR_ORG" >&2
  exit 2
fi

SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEST=/vol2/1000/Docker/moontvplus-custom/auto-update

OWNER_LOWER="$(printf '%s' "$OWNER" | tr '[:upper:]' '[:lower:]')"

mkdir -p "$DEST"
cp -a "$SRC/." "$DEST/"

sed "s#ghcr.io/YOUR_GITHUB_OWNER/moontvplus-custom:stable#ghcr.io/${OWNER_LOWER}/moontvplus-custom:stable#" \
  "$SRC/config.env.example" > "$DEST/config.env"

chmod +x "$DEST"/*.sh "$DEST"/*.py
mkdir -p "$DEST/state" "$DEST/backups" "$DEST/logs"

echo "Installed to: $DEST"
echo "Image: ghcr.io/${OWNER_LOWER}/moontvplus-custom:stable"
echo
echo "Next:"
echo "  1) Make the GHCR package public, OR docker login ghcr.io on the NAS."
echo "  2) Run: $DEST/update-moontv.sh"
echo "  3) Verify MoonTV."
echo "  4) Then run: $DEST/enable-auto-update.sh"
