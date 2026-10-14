/* eslint-disable @typescript-eslint/no-explicit-any,no-console */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthInfoFromCookie } from '@/lib/auth';
import { getAvailableApiSites } from '@/lib/config';

export const runtime = 'nodejs';

const PER_SOURCE_LIMIT = 24;
const HOME_LIMIT = 24;
const SOURCE_TIMEOUT_MS = 6500;

type ApiSite = {
  key: string;
  name: string;
  api: string;
  detail?: string;
  proxyMode?: boolean;
};

type AdultHomeItem = {
  id: string;
  source: string;
  source_name: string;
  title: string;
  poster: string;
  year: string;
  type_name: string;
  desc: string;
  douban_id: number;
  episodes: string[];
  episodes_titles: string[];
  source_count: number;
  source_names: string[];
  updated_at: string;
  proxyMode: boolean;
};

function normalizeTitle(value: string): string {
  return (value || '')
    .toLowerCase()
    .replace(/[\s\u3000]/g, '')
    .replace(/[()（）[\]【】{}「」『』<>《》]/g, '')
    .replace(/[^\w\u4e00-\u9fa5]/g, '');
}

function extractEpisodes(playUrl?: string): {
  episodes: string[];
  titles: string[];
} {
  const episodes: string[] = [];
  const titles: string[] = [];
  if (!playUrl) return { episodes, titles };

  let bestEpisodes: string[] = [];
  let bestTitles: string[] = [];

  String(playUrl)
    .split('$$$')
    .forEach((group) => {
      const groupEpisodes: string[] = [];
      const groupTitles: string[] = [];

      group.split('#').forEach((entry) => {
        const parts = entry.split('$');
        if (
          parts.length === 2 &&
          /\.m3u8(?:[?#].*)?$/i.test(parts[1].trim())
        ) {
          groupTitles.push(parts[0].trim());
          groupEpisodes.push(parts[1].trim());
        }
      });

      if (groupEpisodes.length > bestEpisodes.length) {
        bestEpisodes = groupEpisodes;
        bestTitles = groupTitles;
      }
    });

  return { episodes: bestEpisodes, titles: bestTitles };
}

async function fetchLatestFromSite(site: ApiSite): Promise<AdultHomeItem[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SOURCE_TIMEOUT_MS);
  const joiner = site.api.includes('?') ? '&' : '?';
  const url = site.api + joiner + 'ac=videolist&pg=1';

  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent':
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36',
        Accept: 'application/json',
      },
      signal: controller.signal,
      cache: 'no-store',
    });

    if (!response.ok) return [];

    const data = await response.json();
    if (!data || !Array.isArray(data.list)) return [];

    return data.list
      .slice(0, PER_SOURCE_LIMIT)
      .map((item: any) => {
        const parsed = extractEpisodes(item.vod_play_url);
        const yearMatch = String(item.vod_year || '').match(/\d{4}/);
        return {
          id: String(item.vod_id ?? ''),
          source: site.key,
          source_name: site.name,
          title: String(item.vod_name || '').trim().replace(/\s+/g, ' '),
          poster: String(item.vod_pic || ''),
          year: yearMatch?.[0] || '',
          type_name: String(item.type_name || item.vod_class || ''),
          desc: String(item.vod_content || '').replace(/<[^>]+>/g, ''),
          douban_id: Number(item.vod_douban_id || 0),
          episodes: parsed.episodes,
          episodes_titles: parsed.titles,
          source_count: 1,
          source_names: [site.name],
          updated_at: String(
            item.vod_time || item.vod_time_add || item.vod_time_hits || ''
          ),
          proxyMode: !!site.proxyMode,
        } satisfies AdultHomeItem;
      })
      .filter((item: AdultHomeItem) => item.id && item.title);
  } catch (error) {
    console.warn('[AdultHome] source failed: ' + site.name, error);
    return [];
  } finally {
    clearTimeout(timer);
  }
}

export async function GET(request: NextRequest) {
  const authInfo = getAuthInfoFromCookie(request);
  if (!authInfo || !authInfo.username) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const sites = (await getAvailableApiSites(
    authInfo.username,
    true
  )) as ApiSite[];

  if (sites.length === 0) {
    return NextResponse.json(
      { results: [], sourceCount: 0 },
      { headers: { 'Cache-Control': 'private, max-age=120' } }
    );
  }

  const batches = await Promise.all(sites.map((site) => fetchLatestFromSite(site)));
  const flat = batches.flat();

  const grouped = new Map<
    string,
    { representative: AdultHomeItem; sources: Set<string>; sourceNames: Set<string> }
  >();

  flat.forEach((item) => {
    const titleKey = normalizeTitle(item.title);
    if (!titleKey) return;
    const key = titleKey + '|' + (item.year || 'unknown');

    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, {
        representative: item,
        sources: new Set([item.source]),
        sourceNames: new Set([item.source_name]),
      });
      return;
    }

    existing.sources.add(item.source);
    existing.sourceNames.add(item.source_name);

    const current = existing.representative;
    const currentScore =
      (current.poster ? 2 : 0) + (current.episodes.length > 0 ? 3 : 0);
    const nextScore =
      (item.poster ? 2 : 0) + (item.episodes.length > 0 ? 3 : 0);

    if (nextScore > currentScore) {
      existing.representative = item;
    }
  });

  const results = Array.from(grouped.values())
    .map(({ representative, sources, sourceNames }) => ({
      ...representative,
      source_count: sources.size,
      source_names: Array.from(sourceNames),
    }))
    .sort((a, b) => {
      if (b.source_count !== a.source_count) {
        return b.source_count - a.source_count;
      }
      if (b.episodes.length !== a.episodes.length) {
        return b.episodes.length - a.episodes.length;
      }
      return String(b.updated_at).localeCompare(String(a.updated_at));
    })
    .slice(0, HOME_LIMIT);

  return NextResponse.json(
    { results, sourceCount: sites.length },
    {
      headers: {
        'Cache-Control': 'private, max-age=300',
      },
    }
  );
}
