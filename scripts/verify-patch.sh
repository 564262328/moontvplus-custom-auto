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
SEARCH_SCRIPT="$AUTOMATION_ROOT/scripts/apply-search-customization.py"
SIDEBAR_SCRIPT="$AUTOMATION_ROOT/scripts/apply-sidebar-customization.py"
COVERAGE_SCRIPT="$AUTOMATION_ROOT/scripts/apply-search-coverage.py"
ADULT_HOME_SCRIPT="$AUTOMATION_ROOT/scripts/apply-adult-home-customization.py"
ADULT_NAV_SCRIPT="$AUTOMATION_ROOT/scripts/apply-adult-navigation.py"
OVERLAY_DIR="$AUTOMATION_ROOT/custom/overlays"

[[ -f "$CSS_FILE" ]] || { echo "ERROR: missing $CSS_FILE" >&2; exit 2; }
[[ -f "$VIDEO_SCRIPT" ]] || { echo "ERROR: missing $VIDEO_SCRIPT" >&2; exit 2; }
[[ -f "$SEARCH_SCRIPT" ]] || { echo "ERROR: missing $SEARCH_SCRIPT" >&2; exit 2; }
[[ -f "$SIDEBAR_SCRIPT" ]] || { echo "ERROR: missing $SIDEBAR_SCRIPT" >&2; exit 2; }
[[ -f "$COVERAGE_SCRIPT" ]] || { echo "ERROR: missing $COVERAGE_SCRIPT" >&2; exit 2; }
[[ -f "$ADULT_HOME_SCRIPT" ]] || { echo "ERROR: missing $ADULT_HOME_SCRIPT" >&2; exit 2; }
[[ -f "$ADULT_NAV_SCRIPT" ]] || { echo "ERROR: missing $ADULT_NAV_SCRIPT" >&2; exit 2; }
[[ -d "$OVERLAY_DIR" ]] || { echo "ERROR: missing $OVERLAY_DIR" >&2; exit 2; }

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

echo "Applying semantic search page hooks..."
if [[ -f src/components/SearchPageClient.tsx ]]; then
  SEARCH_TARGET=src/components/SearchPageClient.tsx
else
  SEARCH_TARGET=src/app/search/page.tsx
fi
python3 "$SEARCH_SCRIPT" "$SEARCH_TARGET"

echo "Applying semantic Sidebar hooks..."
python3 "$SIDEBAR_SCRIPT" src/components/Sidebar.tsx

echo "Applying coverage-oriented downstream search compatibility..."
python3 "$COVERAGE_SCRIPT" src/lib/downstream.ts

echo "Applying five-row home layout + adult aggregation hooks..."
python3 "$ADULT_HOME_SCRIPT" src/app/page.tsx

echo "Applying adult navigation + special-source context preservation..."
python3 "$ADULT_NAV_SCRIPT" .

echo "Applying custom overlay files..."
cp -a "$OVERLAY_DIR/." .

git add   src/app/globals.css   src/components/VideoCard.tsx   "$SEARCH_TARGET"   src/components/Sidebar.tsx   src/lib/downstream.ts   src/lib/special-source.client.ts   src/app/page.tsx   src/app/under/page.tsx   src/app/api/adult/home/route.ts

test -f Dockerfile.preview
grep -q 'MoonTVPlus Custom UI V1.7 Desktop Focus' src/app/globals.css
grep -q 'MoonTVPlus Custom UI V1.7.1 Detail Grid Hotfix' src/app/globals.css
grep -q 'media-card-rating' src/components/VideoCard.tsx
grep -q 'media-card-title' src/components/VideoCard.tsx
grep -q 'moontv-search-input' "$SEARCH_TARGET"
grep -q 'pro-sidebar-personal' src/components/Sidebar.tsx
grep -q 'pro-sidebar-offset' src/components/Sidebar.tsx
grep -q 'MoonTV Custom Coverage Search' src/lib/downstream.ts
grep -Fq 'searchPlayData.length === 0' src/lib/downstream.ts
grep -q "case 'hotAdult':" src/app/page.tsx
grep -q "case 'hotAnime':" src/app/page.tsx
grep -q "label: '成人'" src/components/Sidebar.tsx
grep -q 'recognize explicit special-source play links' src/lib/special-source.client.ts
grep -q "getAvailableApiSites(" src/app/api/adult/home/route.ts
grep -q "SearchPageClient searchBase='/under'" src/app/under/page.tsx

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
