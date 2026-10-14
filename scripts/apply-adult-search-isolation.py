#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
targets = {
    root / "src/app/api/search/route.ts": 1,
    root / "src/app/api/search/ws/route.ts": 2,
}

old = "if (!config.SiteConfig.DisableYellowFilter) {"
new = "if (!specialOnly && !config.SiteConfig.DisableYellowFilter) {"

for path, expected in targets.items():
    if not path.exists():
        raise SystemExit(f"ERROR: adult search-isolation target missing: {path}")

    text = path.read_text(encoding="utf-8")
    if new in text and old not in text:
        continue

    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"ERROR: expected {expected} yellow-filter guards in {path}, found {count}. "
            "Upstream changed; stop instead of guessing."
        )

    text = text.replace(old, new)
    if text.count(new) != expected:
        raise SystemExit(f"ERROR: adult search filter bypass not applied cleanly: {path}")

    path.write_text(text, encoding="utf-8")

print("Adult special-source search bypasses normal yellow filtering safely.")
