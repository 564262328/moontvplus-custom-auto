#!/usr/bin/env python3
"""Fail-closed, special-source-only layout improvements for SourceSearchPage."""
from pathlib import Path
import sys

def transform(source: str) -> str:
    replacements = [
        (
            "<PageLayout activePath='/source-search'>",
            "<PageLayout activePath='/source-search'>",
        ),
        (
            "<div className='px-4 sm:px-10 py-4 sm:py-8 overflow-visible mb-10'>",
            "<div className={isSpecialVersion ? 'adult-library-page px-4 sm:px-8 py-5 sm:py-8 overflow-visible mb-10' : 'px-4 sm:px-10 py-4 sm:py-8 overflow-visible mb-10'}>",
        ),
        (
            "<div className='mb-6'>\n          <h1 className='flex items-center gap-2 text-2xl font-bold text-gray-800 dark:text-gray-200'>\n            源站寻片",
            "<div className={isSpecialVersion ? 'adult-library-heading mb-6' : 'mb-6'}>\n          <h1 className='flex items-center gap-2 text-2xl font-bold text-gray-800 dark:text-gray-200'>\n            {isSpecialVersion ? '成人片库' : '源站寻片'}",
        ),
        (
            "<div className='max-w-4xl mx-auto mb-8 space-y-6'>",
            "<div className={isSpecialVersion ? 'adult-library-filters max-w-6xl mx-auto mb-8 space-y-6' : 'max-w-4xl mx-auto mb-8 space-y-6'}>",
        ),
        (
            "<div className='max-w-[95%] mx-auto mt-8'>",
            "<div className={isSpecialVersion ? 'adult-library-results max-w-6xl mx-auto mt-7' : 'max-w-[95%] mx-auto mt-8'}>",
        ),
        (
            "<div className='grid grid-cols-3 gap-x-2 gap-y-14 sm:gap-y-20 px-0 sm:px-2 sm:grid-cols-[repeat(auto-fill,_minmax(11rem,_1fr))] sm:gap-x-8'>",
            "<div className={isSpecialVersion ? 'adult-library-grid grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-x-4 gap-y-10 sm:gap-x-5 px-0 sm:px-2' : 'grid grid-cols-3 gap-x-2 gap-y-14 sm:gap-y-20 px-0 sm:px-2 sm:grid-cols-[repeat(auto-fill,_minmax(11rem,_1fr))] sm:gap-x-8'}>",
        ),
    ]
    for before, after in replacements:
        if before == after:
            continue
        if after in source:
            continue
        if source.count(before) != 1:
            raise ValueError(f"source-search UI anchor changed (found {source.count(before)}): {before[:90]!r}")
        source = source.replace(before, after, 1)
    for marker in ("adult-library-page", "adult-library-heading", "adult-library-filters", "adult-library-results", "adult-library-grid"):
        if source.count(marker) != 1:
            raise ValueError(f"missing or duplicate special-only marker: {marker}")
    return source

def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-adult-library-ui.py SOURCE_SEARCH_PAGE")
    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    print("Adult library layout applied without changing normal search or isolation.")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
