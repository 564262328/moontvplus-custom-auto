#!/usr/bin/env bash
set -euo pipefail

UPSTREAM_DIR="${1:-upstream}"
PATCH_FILE="${2:-custom/custom-ui-v1.7.1.patch}"

if [[ ! -d "$UPSTREAM_DIR/.git" ]]; then
  echo "ERROR: upstream git checkout not found: $UPSTREAM_DIR" >&2
  exit 2
fi
if [[ ! -f "$PATCH_FILE" ]]; then
  echo "ERROR: patch not found: $PATCH_FILE" >&2
  exit 2
fi

cd "$UPSTREAM_DIR"
git reset --hard HEAD
git clean -fdx

echo "Applying custom UI patch..."

if git apply --3way --index "../$PATCH_FILE"; then
  echo "Patch applied with git 3-way."
else
  echo "3-way apply was unavailable or failed; trying a strict direct apply..."
  git reset --hard HEAD
  git clean -fdx
  if git apply --check "../$PATCH_FILE"; then
    git apply --index "../$PATCH_FILE"
    echo "Patch applied directly."
  else
    echo "ERROR: custom patch no longer applies cleanly to this upstream revision." >&2
    echo "The workflow will stop here and will NOT publish a new stable image." >&2
    exit 20
  fi
fi

if grep -RIl --exclude-dir=.git '^<<<<<<< ' . >/dev/null 2>&1; then
  echo "ERROR: conflict markers detected after patch application." >&2
  exit 21
fi

test -f Dockerfile.preview
grep -q 'MoonTVPlus Custom UI V1.7 Desktop Focus' src/app/globals.css
grep -q 'MoonTVPlus Custom UI V1.7.1 Detail Grid Hotfix' src/app/globals.css

# Pin pnpm to package.json packageManager instead of floating "latest".
PNPM_VERSION="$(python3 - <<'PY'
import json
with open("package.json", "r", encoding="utf-8") as f:
    p = json.load(f).get("packageManager", "")
if not p.startswith("pnpm@"):
    raise SystemExit("packageManager does not contain a pnpm version")
print(p.split("@", 1)[1])
PY
)"
sed -i "s/pnpm@latest/pnpm@${PNPM_VERSION}/g" Dockerfile.preview

echo "Patch verification passed."
echo "Pinned pnpm: ${PNPM_VERSION}"
