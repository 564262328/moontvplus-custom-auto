#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/lib/downstream.ts")
if not path.exists():
    raise SystemExit(f"ERROR: MoonTV downstream search target not found: {path}")

text = path.read_text(encoding="utf-8")
marker = "MoonTV Custom Coverage Search"

# 1) Accept HLS URLs that carry query strings/fragments. Upstream currently
#    uses endsWith('.m3u8'), which silently drops otherwise valid HLS entries.
replacements = [
    (
        "episode_title_url[1].endsWith('.m3u8')",
        "/\\.m3u8(?:[?#].*)?$/i.test(episode_title_url[1])",
        2,
    ),
    (
        "episodeTitleUrl[1].endsWith('.m3u8')",
        "/\\.m3u8(?:[?#].*)?$/i.test(episodeTitleUrl[1])",
        1,
    ),
]

for old, new, expected in replacements:
    if old not in text:
        # Idempotency: if the semantic replacement is already present, accept it.
        if new in text:
            continue
        raise SystemExit(
            f"ERROR: coverage search HLS matcher target disappeared: {old!r}. "
            "Upstream changed; stop instead of guessing."
        )
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"ERROR: expected {expected} occurrences of {old!r}, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old, new)

# 2) Keep metadata-only search hits when an API intentionally omits vod_play_url
#    from search responses. The play page already fetches source detail by
#    source+id, so these hits can be resolved lazily after the user opens them.
old_filter = (
    "    // 过滤掉集数为 0 的结果\n"
    "    const results = allResults.filter((result: SearchResult) => result.episodes.length > 0);"
)
new_filter = (
    "    // MoonTV Custom Coverage Search: keep metadata-only hits when the search\n"
    "    // endpoint omits vod_play_url. The play page resolves source+id via the\n"
    "    // detail endpoint on open. If play data was supplied but could not be\n"
    "    // parsed, keep the previous safety behavior and exclude that entry.\n"
    "    const results = allResults.filter((result: SearchResult, index: number) => {\n"
    "      const searchPlayData = String(data.list[index]?.vod_play_url || '').trim();\n"
    "      return result.episodes.length > 0 || searchPlayData.length === 0;\n"
    "    });"
)

if marker not in text:
    count = text.count(old_filter)
    if count != 1:
        raise SystemExit(
            f"ERROR: coverage search result-filter target expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old_filter, new_filter, 1)

checks = [
    marker,
    "/\\.m3u8(?:[?#].*)?$/i.test(episode_title_url[1])",
    "/\\.m3u8(?:[?#].*)?$/i.test(episodeTitleUrl[1])",
    "searchPlayData.length === 0",
]
missing = [item for item in checks if item not in text]
if missing:
    raise SystemExit("ERROR: coverage search markers missing after update: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print(f"Coverage search compatibility applied safely: {path}")
