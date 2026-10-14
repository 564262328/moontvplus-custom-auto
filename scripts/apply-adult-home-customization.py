#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/app/page.tsx")
if not path.exists():
    raise SystemExit(f"ERROR: homepage target not found: {path}")

text = path.read_text(encoding="utf-8")

def replace_once(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: homepage compatibility target {label!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    text = text.replace(old, new, 1)

replace_once(
    "import { getDoubanCategories } from '@/lib/douban.client';",
    "import { getDoubanCategories, getDoubanRecommends } from '@/lib/douban.client';",
    "douban import",
)

replace_once(
    "  const [hotMovies, setHotMovies] = useState<DoubanItem[]>([]);\n"
    "  const [hotTvShows, setHotTvShows] = useState<DoubanItem[]>([]);",
    "  const [hotMovies, setHotMovies] = useState<DoubanItem[]>([]);\n"
    "  const [hotAnime, setHotAnime] = useState<DoubanItem[]>([]);\n"
    "  const [hotAdult, setHotAdult] = useState<any[]>([]);\n"
    "  const [hotTvShows, setHotTvShows] = useState<DoubanItem[]>([]);",
    "adult/anime state",
)

old_modules = """  const [homeModules, setHomeModules] = useState<HomeModule[]>([
    { id: 'hotMovies', name: '热门电影', enabled: true, order: 0 },
    { id: 'hotDuanju', name: '热播短剧', enabled: true, order: 1 },
    { id: 'bangumiCalendar', name: '新番放送', enabled: true, order: 2 },
    { id: 'hotTvShows', name: '热门剧集', enabled: true, order: 3 },
    { id: 'hotVarietyShows', name: '热门综艺', enabled: true, order: 4 },
    { id: 'upcomingContent', name: '即将上映', enabled: true, order: 5 },
  ]);"""
new_modules = """  const [homeModules, setHomeModules] = useState<HomeModule[]>([
    { id: 'hotMovies', name: '热门电影', enabled: true, order: 0 },
    { id: 'hotAnime', name: '热门动漫', enabled: true, order: 1 },
    { id: 'hotTvShows', name: '热门电视剧', enabled: true, order: 2 },
    { id: 'hotVarietyShows', name: '热门综艺', enabled: true, order: 3 },
    { id: 'hotAdult', name: '热门成人', enabled: true, order: 4 },
  ]);"""
replace_once(old_modules, new_modules, "home module order")

old_saved = """    const savedHomeModules = localStorage.getItem('homeModules');
    if (savedHomeModules) {
      try {
        setHomeModules(JSON.parse(savedHomeModules));
      } catch (error) {
        console.error('解析首页模块配置失败:', error);
      }
    }"""
new_saved = """    const preferredHomeModules: HomeModule[] = [
      { id: 'hotMovies', name: '热门电影', enabled: true, order: 0 },
      { id: 'hotAnime', name: '热门动漫', enabled: true, order: 1 },
      { id: 'hotTvShows', name: '热门电视剧', enabled: true, order: 2 },
      { id: 'hotVarietyShows', name: '热门综艺', enabled: true, order: 3 },
      { id: 'hotAdult', name: '热门成人', enabled: true, order: 4 },
    ];

    const savedHomeModules = localStorage.getItem('homeModules');
    if (savedHomeModules) {
      try {
        const parsed = JSON.parse(savedHomeModules) as HomeModule[];
        const desiredIds = preferredHomeModules.map((item) => item.id);
        const parsedIds = parsed.map((item) => item.id);
        const alreadyMigrated =
          desiredIds.length === parsedIds.length &&
          desiredIds.every((id) => parsedIds.includes(id));

        if (alreadyMigrated) {
          setHomeModules(parsed);
        } else {
          const oldById = new Map(parsed.map((item) => [item.id, item]));
          const migrated = preferredHomeModules.map((item) => ({
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
          JSON.stringify(preferredHomeModules)
        );
        setHomeModules(preferredHomeModules);
      }
    } else {
      localStorage.setItem(
        'homeModules',
        JSON.stringify(preferredHomeModules)
      );
      setHomeModules(preferredHomeModules);
    }"""
replace_once(old_saved, new_saved, "saved home layout migration")

replace_once(
    "    const bangumiCache = getCache('homepage_bangumi');\n"
    "    const duanjuCache = getCache('homepage_duanju');",
    "    const bangumiCache = getCache('homepage_bangumi');\n"
    "    const animeCache = getCache('homepage_anime');\n"
    "    const adultCache = getCache('homepage_adult');\n"
    "    const duanjuCache = getCache('homepage_duanju');",
    "homepage cache declarations",
)

replace_once(
    "    if (bangumiCache?.data) setBangumiCalendarData(bangumiCache.data);\n"
    "    if (duanjuCache?.data) setHotDuanju(duanjuCache.data);",
    "    if (bangumiCache?.data) setBangumiCalendarData(bangumiCache.data);\n"
    "    if (animeCache?.data) setHotAnime(animeCache.data);\n"
    "    if (adultCache?.data) setHotAdult(adultCache.data);\n"
    "    if (duanjuCache?.data) setHotDuanju(duanjuCache.data);",
    "homepage cache hydration",
)

replace_once(
    "      varietyCache ||\n"
    "      bangumiCache ||\n"
    "      duanjuCache ||",
    "      varietyCache ||\n"
    "      bangumiCache ||\n"
    "      animeCache ||\n"
    "      adultCache ||\n"
    "      duanjuCache ||",
    "homepage cache presence",
)

replace_once(
    "      !varietyCache ||\n"
    "      varietyCache.expired ||\n"
    "      !bangumiCache ||",
    "      !varietyCache ||\n"
    "      varietyCache.expired ||\n"
    "      !animeCache ||\n"
    "      animeCache.expired ||\n"
    "      !adultCache ||\n"
    "      adultCache.expired ||\n"
    "      !bangumiCache ||",
    "homepage cache refresh conditions",
)

replace_once(
    """          const [
            moviesData,
            tvShowsData,
            varietyShowsData,
            bangumiCalendarData,
          ] = await Promise.all([""",
    """          const [
            moviesData,
            tvShowsData,
            varietyShowsData,
            animeData,
            bangumiCalendarData,
          ] = await Promise.all([""",
    "homepage promise destructuring",
)

anime_anchor = """            getDoubanCategories({
              kind: 'tv',
              category: 'show',
              type: 'show',
            }).catch((error) => {
              console.error('获取热门综艺数据失败:', error);
              return null;
            }),
            GetBangumiCalendarData().catch((error) => {"""
anime_replacement = """            getDoubanCategories({
              kind: 'tv',
              category: 'show',
              type: 'show',
            }).catch((error) => {
              console.error('获取热门综艺数据失败:', error);
              return null;
            }),
            getDoubanRecommends({
              kind: 'tv',
              pageLimit: 25,
              pageStart: 0,
              category: '动画',
              format: '电视剧',
              region: '',
              year: '',
              platform: '',
              sort: 'T',
              label: '',
            }).catch((error) => {
              console.error('获取热门动漫数据失败:', error);
              return null;
            }),
            GetBangumiCalendarData().catch((error) => {"""
replace_once(anime_anchor, anime_replacement, "anime homepage request")

variety_block = """          if (varietyShowsData?.code === 200) {
            setHotVarietyShows(varietyShowsData.list);
            if (varietyShowsData.list && varietyShowsData.list.length > 0) {
              setCache('homepage_variety', varietyShowsData.list);
            }
          }
          setBangumiCalendarData(bangumiCalendarData);"""
variety_replacement = """          if (varietyShowsData?.code === 200) {
            setHotVarietyShows(varietyShowsData.list);
            if (varietyShowsData.list && varietyShowsData.list.length > 0) {
              setCache('homepage_variety', varietyShowsData.list);
            }
          }
          if (animeData?.code === 200) {
            setHotAnime(animeData.list);
            if (animeData.list && animeData.list.length > 0) {
              setCache('homepage_anime', animeData.list);
            }
          }
          setBangumiCalendarData(bangumiCalendarData);"""
replace_once(variety_block, variety_replacement, "anime homepage cache")

adult_anchor = """          if (bangumiCalendarData && bangumiCalendarData.length > 0) {
            setCache('homepage_bangumi', bangumiCalendarData);
          }

          try {
            const duanjuResponse = await fetch('/api/duanju/recommends');"""
adult_replacement = """          if (bangumiCalendarData && bangumiCalendarData.length > 0) {
            setCache('homepage_bangumi', bangumiCalendarData);
          }

          try {
            const adultResponse = await fetch('/api/adult/home');
            if (adultResponse.ok) {
              const adultResult = await adultResponse.json();
              if (
                Array.isArray(adultResult.results) &&
                adultResult.results.length > 0
              ) {
                setHotAdult(adultResult.results);
                setCache('homepage_adult', adultResult.results);
              }
            }
          } catch (error) {
            console.error('获取成人聚合数据失败:', error);
          }

          try {
            const duanjuResponse = await fetch('/api/duanju/recommends');"""
replace_once(adult_anchor, adult_replacement, "adult homepage request")

hot_anime_case = """
      case 'hotAnime':
        return (
          <section key='hotAnime' className='home-section mb-8'>
            <div className='section-heading-row mb-4 flex items-center justify-between'>
              <h2 className='section-heading text-xl font-bold text-gray-800 dark:text-gray-200'>
                热门动漫
              </h2>
              <Link
                href='/douban?type=anime'
                className='section-more flex items-center text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
              >
                查看更多
                <ChevronRight className='w-4 h-4 ml-1' />
              </Link>
            </div>
            <ScrollableRow>
              {loading
                ? Array.from({ length: 8 }).map((_, index) => (
                    <div
                      key={index}
                      className='min-w-[96px] w-24 sm:min-w-[180px] sm:w-44'
                    >
                      <div className='aspect-[2/3] bg-gray-200 dark:bg-gray-700 rounded-lg animate-pulse mb-2' />
                      <div className='h-4 bg-gray-200 dark:bg-gray-700 rounded animate-pulse w-3/4' />
                    </div>
                  ))
                : hotAnime.map((anime) => (
                    <div
                      key={anime.id}
                      className='min-w-[96px] w-24 sm:min-w-[180px] sm:w-44'
                    >
                      <VideoCard
                        id={anime.id}
                        poster={anime.poster}
                        title={anime.title}
                        year={anime.year}
                        rate={anime.rate}
                        type='tv'
                        isAnime={true}
                        from='douban'
                        douban_id={anime.id ? parseInt(anime.id) : undefined}
                      />
                    </div>
                  ))}
            </ScrollableRow>
          </section>
        );

"""
if "case 'hotAnime':" not in text:
    anchor = "      case 'hotDuanju':"
    if text.count(anchor) != 1:
        raise SystemExit("ERROR: hotDuanju case anchor changed; stop instead of guessing.")
    text = text.replace(anchor, hot_anime_case + anchor, 1)

hot_adult_case = """
      case 'hotAdult':
        if (hotAdult.length === 0) return null;
        return (
          <section key='hotAdult' className='home-section mb-8'>
            <div className='section-heading-row mb-4 flex items-center justify-between'>
              <h2 className='section-heading text-xl font-bold text-gray-800 dark:text-gray-200'>
                热门成人
              </h2>
              <Link
                href='/under'
                className='section-more flex items-center text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
              >
                查看更多
                <ChevronRight className='w-4 h-4 ml-1' />
              </Link>
            </div>
            <ScrollableRow>
              {hotAdult.map((item) => (
                <div
                  key={item.source + '-' + item.id}
                  className='min-w-[96px] w-24 sm:min-w-[180px] sm:w-44'
                >
                  <VideoCard
                    id={item.id}
                    source={item.source}
                    poster={item.poster}
                    title={item.title}
                    year={item.year}
                    type='movie'
                    from='search'
                    source_name={item.source_name}
                    source_names={item.source_names}
                    episodes={item.episodes?.length}
                    douban_id={item.douban_id}
                    cmsData={{
                      desc: item.desc,
                      episodes: item.episodes,
                      episodes_titles: item.episodes_titles,
                    }}
                  />
                </div>
              ))}
            </ScrollableRow>
          </section>
        );

"""
if "case 'hotAdult':" not in text:
    anchor = "      case 'upcomingContent':"
    if text.count(anchor) != 1:
        raise SystemExit("ERROR: upcomingContent case anchor changed; stop instead of guessing.")
    text = text.replace(anchor, hot_adult_case + anchor, 1)

required = [
    "case 'hotAnime':",
    "case 'hotAdult':",
    "fetch('/api/adult/home')",
    "{ id: 'hotAdult', name: '热门成人', enabled: true, order: 4 }",
    "getDoubanRecommends({",
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit("ERROR: adult homepage markers missing: " + ", ".join(missing))

path.write_text(text, encoding="utf-8")
print(f"Adult/home desktop layout applied safely: {path}")
