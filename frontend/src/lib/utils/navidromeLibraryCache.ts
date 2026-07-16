import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import type { NavidromeAlbumSummary, NavidromeLibraryStats } from '$lib/types';
import { clearLocalStorageNamespace, createLocalStorageCache } from '$lib/utils/localStorageCache';

type NavidromeSidebarData = {
	recentAlbums: NavidromeAlbumSummary[];
	favoriteAlbums: NavidromeAlbumSummary[];
	genres: string[];
	stats: NavidromeLibraryStats | null;
};

type NavidromeAlbumsListData = {
	items: NavidromeAlbumSummary[];
	total: number;
};

const navidromeSidebarCache = createLocalStorageCache<NavidromeSidebarData>(
	CACHE_KEYS.NAVIDROME_SIDEBAR,
	CACHE_TTL.NAVIDROME_SIDEBAR
);

const navidromeAlbumsListCache = createLocalStorageCache<NavidromeAlbumsListData>(
	CACHE_KEYS.NAVIDROME_ALBUMS_LIST,
	CACHE_TTL.NAVIDROME_ALBUMS_LIST,
	{ maxEntries: 80 }
);

const navidromeFolderScopeCache = createLocalStorageCache<string>(
	CACHE_KEYS.NAVIDROME_FOLDER_SCOPE,
	CACHE_TTL.NAVIDROME_ALBUMS_LIST,
	{ maxEntries: 20 }
);

const scopedKey = (userId: string, scopeRevision: string, suffix?: string) =>
	[userId, scopeRevision, suffix]
		.filter((value): value is string => Boolean(value))
		.map(encodeURIComponent)
		.join(':');

export const getNavidromeFolderScopeRevision = (userId: string) =>
	navidromeFolderScopeCache.get(userId)?.data ?? 'unresolved';
export const setNavidromeFolderScopeRevision = (userId: string, revision: string) =>
	navidromeFolderScopeCache.set(revision, userId);

export const getNavidromeSidebarCachedData = (userId: string, scopeRevision: string) =>
	navidromeSidebarCache.get(scopedKey(userId, scopeRevision));
export const setNavidromeSidebarCachedData = (
	data: NavidromeSidebarData,
	userId: string,
	scopeRevision: string
) => navidromeSidebarCache.set(data, scopedKey(userId, scopeRevision));
export const isNavidromeSidebarCacheStale = navidromeSidebarCache.isStale;

export const getNavidromeAlbumsListCachedData = (
	userId: string,
	scopeRevision: string,
	key: string
) => navidromeAlbumsListCache.get(scopedKey(userId, scopeRevision, key));
export const setNavidromeAlbumsListCachedData = (
	data: NavidromeAlbumsListData,
	userId: string,
	scopeRevision: string,
	key: string
) => navidromeAlbumsListCache.set(data, scopedKey(userId, scopeRevision, key));
export const isNavidromeAlbumsListCacheStale = navidromeAlbumsListCache.isStale;

export function clearNavidromeLocalCaches(): void {
	clearLocalStorageNamespace(CACHE_KEYS.NAVIDROME_SIDEBAR);
	clearLocalStorageNamespace(CACHE_KEYS.NAVIDROME_ALBUMS_LIST);
	clearLocalStorageNamespace(CACHE_KEYS.NAVIDROME_FOLDER_SCOPE);
	clearLocalStorageNamespace(CACHE_KEYS.ALBUM_SOURCE_MATCH_CACHE);
}
