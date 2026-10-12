#!/usr/bin/env python3
from pathlib import Path
import re
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "src/components/Sidebar.tsx")
text = path.read_text(encoding="utf-8")

def replace_once(old: str, new: str, marker: str) -> None:
    global text
    if marker in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: Sidebar compatibility target for {marker!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old, new, 1)

# Ensure the icons used by the custom personal shortcuts are imported.
m = re.search(r"import \{([^}]*)\} from 'lucide-react';", text)
if not m:
    raise SystemExit("ERROR: lucide-react import not found in Sidebar")
icons = [x.strip() for x in m.group(1).split(",") if x.strip()]
changed = False
for icon in ("History", "Settings"):
    if icon not in icons:
        icons.append(icon)
        changed = True
if changed:
    icons = sorted(set(icons))
    text = text[:m.start()] + "import { " + ", ".join(icons) + " } from 'lucide-react';" + text[m.end():]

replace_once(
    "className='flex items-center justify-center h-16 select-none hover:opacity-80 transition-opacity duration-200'",
    "className='pro-logo flex items-center justify-center h-16 select-none hover:opacity-90 transition-opacity duration-200'",
    "pro-logo flex",
)
replace_once(
    "className='text-2xl font-bold text-green-600 tracking-tight'",
    "className='pro-logo-text text-2xl font-bold text-green-600 tracking-tight'",
    "pro-logo-text",
)

if "className={`pro-sidebar " not in text:
    old = """          data-sidebar
          className={`fixed top-0 left-0 h-screen"""
    new = """          data-sidebar
          data-collapsed={isCollapsed ? 'true' : 'false'}
          className={`pro-sidebar fixed top-0 left-0 h-screen"""
    if text.count(old) != 1:
        raise SystemExit("ERROR: Sidebar main aside target changed; stop instead of guessing.")
    text = text.replace(old, new, 1)

nav_prefix = "className={`group flex items-center rounded-lg"
if "className={`pro-nav-item group flex items-center rounded-lg" not in text:
    count = text.count(nav_prefix)
    if count < 3:
        raise SystemExit(
            f"ERROR: expected at least 3 Sidebar navigation class targets, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(nav_prefix, "className={`pro-nav-item group flex items-center rounded-lg")

if "pro-sidebar-personal" not in text:
    anchor = "\n          </div>\n        </aside>"
    pos = text.rfind(anchor)
    if pos < 0:
        raise SystemExit("ERROR: Sidebar personal-section insertion anchor not found.")
    personal = """
            {/* 个人功能：固定在侧栏底部，随官方 UserMenu 面板联动 */}
            <div className='pro-sidebar-personal mx-2 mb-4 border-t border-white/10 pt-3 dark:border-white/10'>
              <div className='space-y-1'>
                <button
                  type='button'
                  onClick={() =>
                    window.dispatchEvent(new CustomEvent('moontv:open-favorites'))
                  }
                  className='pro-nav-item group flex min-h-[40px] w-full items-center gap-3 rounded-lg px-2 py-2 pl-4 text-sm text-gray-700 transition-colors duration-200 hover:bg-gray-100/30 hover:text-green-600 dark:text-gray-300 dark:hover:text-green-400'
                  aria-label='我的收藏'
                >
                  <div className='flex h-4 w-4 items-center justify-center'>
                    <Star className='h-4 w-4 text-gray-500 transition-colors group-hover:text-green-600 dark:text-gray-400 dark:group-hover:text-green-400' />
                  </div>
                  {!isCollapsed && <span className='whitespace-nowrap'>我的收藏</span>}
                </button>

                <button
                  type='button'
                  onClick={() =>
                    window.dispatchEvent(new CustomEvent('moontv:open-play-records'))
                  }
                  className='pro-nav-item group flex min-h-[40px] w-full items-center gap-3 rounded-lg px-2 py-2 pl-4 text-sm text-gray-700 transition-colors duration-200 hover:bg-gray-100/30 hover:text-green-600 dark:text-gray-300 dark:hover:text-green-400'
                  aria-label='观看记录'
                >
                  <div className='flex h-4 w-4 items-center justify-center'>
                    <History className='h-4 w-4 text-gray-500 transition-colors group-hover:text-green-600 dark:text-gray-400 dark:group-hover:text-green-400' />
                  </div>
                  {!isCollapsed && <span className='whitespace-nowrap'>观看记录</span>}
                </button>

                <button
                  type='button'
                  onClick={() =>
                    window.dispatchEvent(new CustomEvent('moontv:open-settings'))
                  }
                  className='pro-nav-item group flex min-h-[40px] w-full items-center gap-3 rounded-lg px-2 py-2 pl-4 text-sm text-gray-700 transition-colors duration-200 hover:bg-gray-100/30 hover:text-green-600 dark:text-gray-300 dark:hover:text-green-400'
                  aria-label='设置'
                >
                  <div className='flex h-4 w-4 items-center justify-center'>
                    <Settings className='h-4 w-4 text-gray-500 transition-colors group-hover:text-green-600 dark:text-gray-400 dark:group-hover:text-green-400' />
                  </div>
                  {!isCollapsed && <span className='whitespace-nowrap'>设置</span>}
                </button>
              </div>
            </div>
"""
    text = text[:pos] + personal + text[pos:]

if "pro-sidebar-offset" not in text:
    old = """        <div
          className={`transition-all duration-300 sidebar-offset"""
    new = """        <div
          data-collapsed={isCollapsed ? 'true' : 'false'}
          className={`pro-sidebar-offset transition-all duration-300 sidebar-offset"""
    if text.count(old) != 1:
        raise SystemExit("ERROR: Sidebar offset target changed; stop instead of guessing.")
    text = text.replace(old, new, 1)

required = [
    "pro-logo",
    "pro-logo-text",
    "pro-sidebar ",
    "pro-nav-item",
    "pro-sidebar-personal",
    "pro-sidebar-offset",
    "moontv:open-favorites",
    "moontv:open-play-records",
    "moontv:open-settings",
]
missing = [marker for marker in required if marker not in text]
if missing:
    raise SystemExit("ERROR: missing Sidebar custom markers after update: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print("Sidebar custom classes and personal shortcuts applied safely.")
