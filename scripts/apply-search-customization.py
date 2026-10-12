#!/usr/bin/env python3
from pathlib import Path
import sys

candidates = [
    Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/components/SearchPageClient.tsx"),
    Path("src/components/SearchPageClient.tsx"),
    Path("src/app/search/page.tsx"),
]
path = next((p for p in candidates if p.exists()), None)
if path is None:
    raise SystemExit("ERROR: no supported MoonTV search page target found")

text = path.read_text(encoding="utf-8")

replacements = [
    (
        "className='px-4 sm:px-10 py-4 sm:py-8 overflow-visible mb-10'",
        "className='moontv-search-page px-4 sm:px-10 py-4 sm:py-8 overflow-visible mb-10'",
        "moontv-search-page",
    ),
    (
        "className='max-w-2xl mx-auto'",
        "className='moontv-search-form max-w-2xl mx-auto'",
        "moontv-search-form",
    ),
    (
        "className='w-full h-12 rounded-lg bg-gray-50/80 py-3 pl-10 pr-12 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-400 focus:bg-white border border-gray-200/50 shadow-sm dark:bg-gray-800 dark:text-gray-300 dark:placeholder-gray-500 dark:focus:bg-gray-700 dark:border-gray-700'",
        "className='moontv-search-input w-full h-12 rounded-lg bg-gray-50/80 py-3 pl-10 pr-12 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-400 focus:bg-white border border-gray-200/50 shadow-sm dark:bg-gray-800 dark:text-gray-300 dark:placeholder-gray-500 dark:focus:bg-gray-700 dark:border-gray-700'",
        "moontv-search-input",
    ),
]

for old, new, marker in replacements:
    if marker in text:
        continue
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: search compatibility target for {marker!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old, new, 1)

missing = [marker for _, _, marker in replacements if marker not in text]
if missing:
    raise SystemExit("ERROR: missing search custom markers after update: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print(f"Search custom classes applied safely: {path}")
