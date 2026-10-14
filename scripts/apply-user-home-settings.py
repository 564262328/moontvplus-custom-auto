#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/components/UserMenu.tsx")
if not path.exists():
    raise SystemExit(f"ERROR: UserMenu target not found: {path}")

text = path.read_text(encoding="utf-8")

old_defaults = """  const defaultHomeModules: HomeModule[] = [
    { id: 'hotMovies', name: '热门电影', enabled: true, order: 0 },
    { id: 'hotDuanju', name: '热播短剧', enabled: true, order: 1 },
    { id: 'bangumiCalendar', name: '新番放送', enabled: true, order: 2 },
    { id: 'hotTvShows', name: '热门剧集', enabled: true, order: 3 },
    { id: 'hotVarietyShows', name: '热门综艺', enabled: true, order: 4 },
    { id: 'upcomingContent', name: '即将上映', enabled: true, order: 5 },
  ];"""
new_defaults = """  const defaultHomeModules: HomeModule[] = [
    { id: 'hotMovies', name: '热门电影', enabled: true, order: 0 },
    { id: 'hotAnime', name: '热门动漫', enabled: true, order: 1 },
    { id: 'hotTvShows', name: '热门电视剧', enabled: true, order: 2 },
    { id: 'hotVarietyShows', name: '热门综艺', enabled: true, order: 3 },
    { id: 'hotAdult', name: '热门成人', enabled: true, order: 4 },
  ];"""

if "id: 'hotAdult', name: '热门成人'" not in text:
    count = text.count(old_defaults)
    if count != 1:
        raise SystemExit(
            f"ERROR: UserMenu home default target expected once, found {count}."
        )
    text = text.replace(old_defaults, new_defaults, 1)

old_load = """      // 加载首页模块配置
      const savedHomeModules = localStorage.getItem('homeModules');
      if (savedHomeModules !== null) {
        try {
          setHomeModules(JSON.parse(savedHomeModules));
        } catch (error) {
          console.error('解析首页模块配置失败:', error);
        }
      }"""
new_load = """      // 加载首页模块配置；旧版 6 模块布局自动迁移到自定义 5 模块布局。
      const savedHomeModules = localStorage.getItem('homeModules');
      if (savedHomeModules !== null) {
        try {
          const parsed = JSON.parse(savedHomeModules) as HomeModule[];
          const desiredIds = defaultHomeModules.map((item) => item.id);
          const parsedIds = parsed.map((item) => item.id);
          const alreadyMigrated =
            desiredIds.length === parsedIds.length &&
            desiredIds.every((id) => parsedIds.includes(id));

          if (alreadyMigrated) {
            setHomeModules(parsed);
          } else {
            const oldById = new Map(parsed.map((item) => [item.id, item]));
            const migrated = defaultHomeModules.map((item) => ({
              ...item,
              enabled: oldById.get(item.id)?.enabled ?? true,
            }));
            localStorage.setItem('homeModules', JSON.stringify(migrated));
            setHomeModules(migrated);
          }
        } catch (error) {
          console.error('解析首页模块配置失败:', error);
          localStorage.setItem(
            'homeModules',
            JSON.stringify(defaultHomeModules)
          );
          setHomeModules(defaultHomeModules);
        }
      } else {
        localStorage.setItem('homeModules', JSON.stringify(defaultHomeModules));
        setHomeModules(defaultHomeModules);
      }"""

if "旧版 6 模块布局自动迁移" not in text:
    count = text.count(old_load)
    if count != 1:
        raise SystemExit(
            f"ERROR: UserMenu home settings load target expected once, found {count}."
        )
    text = text.replace(old_load, new_load, 1)

required = [
    "id: 'hotAnime', name: '热门动漫'",
    "id: 'hotAdult', name: '热门成人'",
    "旧版 6 模块布局自动迁移",
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit("ERROR: UserMenu adult-home markers missing: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print(f"UserMenu home layout settings applied safely: {path}")
