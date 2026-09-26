#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "src/components/VideoCard.tsx")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "className={`group relative w-full rounded-lg bg-transparent transition-all duration-300 ease-in-out hover:scale-[1.05] hover:z-[500] \${",
        "className={`media-card group relative w-full rounded-lg bg-transparent transition-all duration-300 ease-in-out hover:scale-[1.05] hover:z-[500] \${",
        "media-card",
    ),
    (
        "className={`relative rounded-lg \${",
        "className={`media-card-poster relative rounded-lg \${",
        "media-card-poster",
    ),
    (
        "className='absolute inset-0 overflow-hidden rounded-lg'",
        "className='media-card-image-shell absolute inset-0 overflow-hidden rounded-lg'",
        "media-card-image-shell",
    ),
    (
        "className='absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent transition-opacity duration-300 ease-in-out opacity-0 group-hover:opacity-100'",
        "className='media-card-overlay absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent transition-opacity duration-300 ease-in-out opacity-0 group-hover:opacity-100'",
        "media-card-overlay",
    ),
    (
        "className='absolute top-2 right-2 bg-pink-500 text-white text-xs font-bold w-7 h-7 rounded-full flex items-center justify-center shadow-md transition-all duration-300 ease-out group-hover:scale-110'",
        "className='media-card-rating absolute top-2 right-2 bg-pink-500 text-white text-xs font-bold w-7 h-7 rounded-full flex items-center justify-center shadow-md transition-all duration-300 ease-out group-hover:scale-110'",
        "media-card-rating",
    ),
    (
        "className='mt-1 h-1 w-full bg-gray-200 rounded-full overflow-hidden'",
        "className='media-card-progress-track mt-1 h-1 w-full bg-gray-200 rounded-full overflow-hidden'",
        "media-card-progress-track",
    ),
    (
        "className='h-full bg-green-500 transition-all duration-500 ease-out'",
        "className='media-card-progress h-full bg-green-500 transition-all duration-500 ease-out'",
        "media-card-progress",
    ),
    (
        "className='mt-2 text-center'",
        "className='media-card-caption mt-2 text-center'",
        "media-card-caption",
    ),
    (
        "className='block text-sm font-semibold truncate text-gray-900 dark:text-gray-100 transition-colors duration-300 ease-in-out group-hover:text-green-600 dark:group-hover:text-green-400 peer'",
        "className='media-card-title block text-sm font-semibold truncate text-gray-900 dark:text-gray-100 transition-colors duration-300 ease-in-out group-hover:text-green-600 dark:group-hover:text-green-400 peer'",
        "media-card-title",
    ),
]

for old, new, marker in replacements:
    if marker in text:
        continue
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: VideoCard compatibility target for {marker!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old, new, 1)

missing = [marker for _, _, marker in replacements if marker not in text]
if missing:
    raise SystemExit("ERROR: missing VideoCard custom markers after update: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print("VideoCard custom classes applied safely.")
