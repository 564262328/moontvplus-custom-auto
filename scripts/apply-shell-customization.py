#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
mobile = root / "src/components/MobileHeader.tsx"
layout = root / "src/components/PageLayout.tsx"

if not mobile.exists() or not layout.exists():
    raise SystemExit("ERROR: shell customization targets are missing")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: shell target {label!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    return text.replace(old, new, 1)

# MobileHeader: add stable class hooks without depending on safe-area style syntax.
m = mobile.read_text(encoding="utf-8")
m = replace_once(
    m,
    "className='md:hidden fixed top-0 left-0 right-0 z-[999] w-full bg-white/70 backdrop-blur-xl border-b border-gray-200/50 shadow-sm dark:bg-gray-900/70 dark:border-gray-700/50'",
    "className='mobile-header md:hidden fixed top-0 left-0 right-0 z-[999] w-full bg-white/70 backdrop-blur-xl border-b border-gray-200/50 shadow-sm dark:bg-gray-900/70 dark:border-gray-700/50'",
    "mobile header class",
)
m = replace_once(
    m,
    "className='text-2xl font-bold text-green-600 tracking-tight hover:opacity-80 transition-opacity'",
    "className='mobile-logo text-2xl font-bold text-green-600 tracking-tight hover:opacity-80 transition-opacity'",
    "mobile logo class",
)
mobile.write_text(m, encoding="utf-8")

# PageLayout: stable semantic hooks, preserving upstream safe-area and layout changes.
p = layout.read_text(encoding="utf-8")
p = replace_once(
    p,
    "className='relative w-full min-h-screen overflow-hidden'",
    "className='moontv-shell relative w-full min-h-screen overflow-hidden'",
    "shell class",
)
p = replace_once(
    p,
    "className='relative z-10 flex md:grid md:grid-cols-[auto_1fr] w-full min-h-screen md:min-h-auto'",
    "className='moontv-layout relative z-10 flex md:grid md:grid-cols-[auto_1fr] w-full min-h-screen md:min-h-auto'",
    "layout class",
)
p = replace_once(
    p,
    "className='absolute top-2 right-4 z-20 hidden md:flex items-center gap-2'",
    "className='desktop-top-actions absolute top-3 right-5 z-20 hidden md:flex items-center gap-1.5'",
    "desktop actions",
)
p = replace_once(
    p,
    "<UserMenu />",
    "<UserMenu desktopBridge />",
    "desktop UserMenu bridge",
)
p = replace_once(
    p,
    "className='flex-1 md:min-h-0 mb-14 md:mb-0 md:mt-0 mt-[calc(3rem+var(--safe-top))]'",
    "className='moontv-main flex-1 md:min-h-0 mb-14 md:mb-0 md:mt-0 mt-[calc(3rem+var(--safe-top))]'",
    "main class current safe-top",
) if "mt-[calc(3rem+var(--safe-top))]" in p else replace_once(
    p,
    "className='flex-1 md:min-h-0 mb-14 md:mb-0 md:mt-0 mt-[calc(3rem+env(safe-area-inset-top))]'",
    "className='moontv-main flex-1 md:min-h-0 mb-14 md:mb-0 md:mt-0 mt-[calc(3rem+env(safe-area-inset-top))]'",
    "main class legacy safe-top",
)

required = [
    "moontv-shell",
    "moontv-layout",
    "desktop-top-actions",
    "<UserMenu desktopBridge />",
    "moontv-main",
]
missing = [x for x in required if x not in p]
if missing:
    raise SystemExit("ERROR: PageLayout shell markers missing: " + ", ".join(missing))

layout.write_text(p, encoding="utf-8")
print("Shell customization applied safely.")
