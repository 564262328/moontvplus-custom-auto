#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/app/page.tsx")
if not path.exists():
    raise SystemExit(f"ERROR: homepage polish target not found: {path}")

text = path.read_text(encoding="utf-8")

pairs = [
    ("<section key='hotMovies' className='home-section mb-8'>",
     "<section key='hotMovies' className='home-section home-section-movie mb-8'>"),
    ("<section key='hotAnime' className='home-section mb-8'>",
     "<section key='hotAnime' className='home-section home-section-anime mb-8'>"),
    ("<section key='hotTvShows' className='home-section mb-8'>",
     "<section key='hotTvShows' className='home-section home-section-tv mb-8'>"),
    ("<section key='hotVarietyShows' className='home-section mb-8'>",
     "<section key='hotVarietyShows' className='home-section home-section-variety mb-8'>"),
    ("<section key='hotAdult' className='home-section mb-8'>",
     "<section key='hotAdult' className='home-section home-section-adult mb-8'>"),
]

for old, new in pairs:
    if new in text:
        continue
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: homepage polish anchor expected once, found {count}: {old}"
        )
    text = text.replace(old, new, 1)

required = [
    "home-section-movie",
    "home-section-anime",
    "home-section-tv",
    "home-section-variety",
    "home-section-adult",
]
missing = [marker for marker in required if marker not in text]
if missing:
    raise SystemExit("ERROR: homepage polish markers missing: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print(f"V1.9 homepage semantic classes applied safely: {path}")
