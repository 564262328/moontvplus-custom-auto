#!/usr/bin/env python3
"""Apply V2.1 cinematic desktop-home semantics; refuse unknown upstream markup."""
from pathlib import Path
import sys

CHANNELS = """            {/* V2.1 cinematic channel navigation; ordinary categories only. */}
            <nav className='cinema-channel-nav' aria-label='浏览影视分类'>
              <span className='cinema-channel-label'>探索频道</span>
              <div className='cinema-channel-links'>
                {[
                  { label: '全部推荐', href: '/' },
                  { label: '电影', href: '/douban?type=movie' },
                  { label: '电视剧', href: '/douban?type=tv' },
                  { label: '动漫', href: '/douban?type=anime' },
                  { label: '综艺', href: '/douban?type=show' },
                ].map((channel) => (
                  <Link
                    key={channel.href}
                    href={channel.href}
                    className='cinema-channel-chip'
                  >
                    {channel.label}
                  </Link>
                ))}
              </div>
            </nav>

"""

def apply(source: str) -> str:
    substitutions = [
        ("className='hero-wrap w-full mb-4'", "className='hero-wrap cinema-hero w-full mb-4'"),
        ("className='home-content px-2 sm:px-10 pb-4 sm:pb-8 overflow-visible'",
         "className='home-content cinema-home-content px-2 sm:px-10 pb-4 sm:pb-8 overflow-visible'"),
        ("            {/* 继续观看 */}", CHANNELS + "            {/* 继续观看 */}"),
    ]
    for before, after in substitutions:
        if after in source:
            continue
        count = source.count(before)
        if count != 1:
            raise ValueError(f"V2.1 home anchor expected once, found {count}: {before[:80]}")
        source = source.replace(before, after, 1)
    for marker in ("cinema-hero", "cinema-home-content", "cinema-channel-nav"):
        if source.count(marker) != 1:
            raise ValueError(f"V2.1 marker not unique: {marker}")
    return source

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-cinematic-home.py UPSTREAM_HOME_TSX")
    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    modified = apply(original)
    if original != modified:
        path.write_text(modified, encoding="utf-8")
    print("V2.1 cinematic homepage applied safely.")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
