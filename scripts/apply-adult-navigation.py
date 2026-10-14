#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
sidebar = root / "src/components/Sidebar.tsx"
special = root / "src/lib/special-source.client.ts"

if not sidebar.exists() or not special.exists():
    raise SystemExit("ERROR: adult navigation targets are missing")

sidebar_text = sidebar.read_text(encoding="utf-8")

adult_item = """      {
        icon: Star,
        label: '成人',
        href: SPECIAL_SOURCE_PATH,
      },
"""

variety_block = """      {
        icon: Clover,
        label: '综艺',
        href: '/douban?type=show',
      },
"""

if "label: '成人'" not in sidebar_text:
    count = sidebar_text.count(variety_block)
    if count != 2:
        raise SystemExit(
            f"ERROR: expected 2 Sidebar variety anchors, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    sidebar_text = sidebar_text.replace(variety_block, variety_block + adult_item)

if "label: '成人'" not in sidebar_text or "href: SPECIAL_SOURCE_PATH" not in sidebar_text:
    raise SystemExit("ERROR: adult Sidebar item was not applied")

sidebar.write_text(sidebar_text, encoding="utf-8")

special_text = special.read_text(encoding="utf-8")
old = """export function appendSpecialSourceParam(url: string): string {
  if (!isSpecialSourceContext()) return url;
  if (/[?&]special=1(&|$)/.test(url)) return url;
  const separator = url.includes('?') ? '&' : '?';
  return \`\${url}\${separator}special=1\`;
}"""
new = """export function appendSpecialSourceParam(url: string): string {
  // Preserve the special-source context when navigating from /under, and also
  // recognize explicit special-source play links rendered on the normal home
  // page (for example the custom Adult row).
  let targetIsSpecial = false;
  if (typeof window !== 'undefined') {
    try {
      const parsed = new URL(url, window.location.origin);
      const source = parsed.searchParams.get('source') || '';
      targetIsSpecial = !!source && isSpecialSourceKey(source);
    } catch {
      targetIsSpecial = false;
    }
  }

  if (!isSpecialSourceContext() && !targetIsSpecial) return url;
  if (/[?&]special=1(&|$)/.test(url)) return url;
  const separator = url.includes('?') ? '&' : '?';
  return url + separator + 'special=1';
}"""

if "recognize explicit special-source play links" not in special_text:
    count = special_text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: special-source navigation target expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    special_text = special_text.replace(old, new, 1)

required = [
    "recognize explicit special-source play links",
    "targetIsSpecial",
    "isSpecialSourceKey(source)",
]
missing = [item for item in required if item not in special_text]
if missing:
    raise SystemExit("ERROR: special-source navigation markers missing: " + ", ".join(missing))

special.write_text(special_text, encoding="utf-8")
print("Adult Sidebar and special-source navigation applied safely.")
