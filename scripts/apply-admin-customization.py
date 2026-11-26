#!/usr/bin/env python3
"""Fail-closed semantic CSS hook for MoonTVPlus admin collapsible panels."""
import sys
from pathlib import Path

MODERN_BEFORE = "      {isExpanded && (\n        <div\n          className={\n            contentClassName ||\n            (isParent ? 'px-0.5 md:px-6 py-4' : 'px-6 py-4')\n          }\n        >"
MODERN_AFTER = "      {isExpanded && (\n        <div\n          className={`moontv-admin-tab-content ${\n            contentClassName ||\n            (isParent ? 'px-0.5 md:px-6 py-4' : 'px-6 py-4')\n          }`}\n        >"
LEGACY_BEFORE = "      {isExpanded && (\n        <div className={isParent ? 'px-0.5 md:px-6 py-4' : 'px-6 py-4'}>"
LEGACY_AFTER = "      {isExpanded && (\n        <div\n          className={`moontv-admin-tab-content ${\n            isParent ? 'px-0.5 md:px-6 py-4' : 'px-6 py-4'\n          }`}\n        >"
MARKER = "moontv-admin-tab-content"

def transform(source: str) -> str:
    if MARKER in source:
        if source.count(MARKER) == 1 and (MODERN_AFTER in source or LEGACY_AFTER in source):
            return source
        raise ValueError("admin customization marker already present but structure is unexpected")
    candidates = [(MODERN_BEFORE, MODERN_AFTER), (LEGACY_BEFORE, LEGACY_AFTER)]
    found = [(before, after) for before, after in candidates if source.count(before) == 1]
    if len(found) != 1:
        raise ValueError("admin collapsible content anchor absent or ambiguous; refusing to publish")
    before, after = found[0]
    return source.replace(before, after, 1)

def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-admin-customization.py PATH_TO_ADMIN_PAGE")
    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    print("Admin collapsible content CSS hook verified.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
