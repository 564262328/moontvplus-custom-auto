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

UPSTREAM_DIR="$(cd "$UPSTREAM_DIR" && pwd)"
PATCH_FILE="$(cd "$(dirname "$PATCH_FILE")" && pwd)/$(basename "$PATCH_FILE")"
AUTOMATION_ROOT="$(cd "$(dirname "$PATCH_FILE")/.." && pwd)"
CSS_FILE="$AUTOMATION_ROOT/custom/custom-ui-v1.7.1.css"
VIDEO_SCRIPT="$AUTOMATION_ROOT/scripts/apply-videocard-customization.py"

[[ -f "$CSS_FILE" ]] || { echo "ERROR: missing $CSS_FILE" >&2; exit 2; }
[[ -f "$VIDEO_SCRIPT" ]] || { echo "ERROR: missing $VIDEO_SCRIPT" >&2; exit 2; }

cd "$UPSTREAM_DIR"
git reset --hard HEAD
git clean -fdx

echo "Applying structural custom UI patch..."

if git apply --3way --index "$PATCH_FILE"; then
  echo "Structural patch applied with git 3-way."
else
  echo "3-way apply was unavailable or failed; trying a strict direct apply..."
  git reset --hard HEAD
  git clean -fdx
  if git apply --check "$PATCH_FILE"; then
    git apply --index "$PATCH_FILE"
    echo "Structural patch applied directly."
  else
    echo "ERROR: structural custom patch no longer applies cleanly to this upstream revision." >&2
    echo "The workflow will stop here and will NOT publish a new stable image." >&2
    exit 20
  fi
fi

if grep -RIl --exclude-dir=.git '^<<<<<<< ' . >/dev/null 2>&1; then
  echo "ERROR: conflict markers detected after structural patch application." >&2
  exit 21
fi

echo "Appending versioned custom CSS without relying on upstream globals.css line numbers..."
if ! grep -q 'MoonTVPlus Custom UI V1.7 Desktop Focus' src/app/globals.css; then
  printf '\n\n' >> src/app/globals.css
  cat "$CSS_FILE" >> src/app/globals.css
fi

echo "Applying semantic VideoCard class hooks..."
python3 "$VIDEO_SCRIPT" src/components/VideoCard.tsx

git add src/app/globals.css src/components/VideoCard.tsx

test -f Dockerfile.preview
grep -q 'MoonTVPlus Custom UI V1.7 Desktop Focus' src/app/globals.css
grep -q 'MoonTVPlus Custom UI V1.7.1 Detail Grid Hotfix' src/app/globals.css
grep -q 'media-card-rating' src/components/VideoCard.tsx
grep -q 'media-card-title' src/components/VideoCard.tsx

git diff --cached --check

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
git add Dockerfile.preview

git diff --cached --check

echo "Patch verification passed."
echo "Pinned pnpm: ${PNPM_VERSION}"
