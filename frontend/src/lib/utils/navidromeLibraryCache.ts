import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import type { NavidromeAlbumSummary, NavidromeLibraryStats } from '$lib/types';
import { createLocalStorageCache } from '$lib/utils/localStorageCache';

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

export const getNavidromeSidebarCachedData = navidromeSidebarCache.get;
export const setNavidromeSidebarCachedData = navidromeSidebarCache.set;
export const isNavidromeSidebarCacheStale = navidromeSidebarCache.isStale;

export const getNavidromeAlbumsListCachedData = navidromeAlbumsListCache.get;
export const setNavidromeAlbumsListCachedData = navidromeAlbumsListCache.set;
export const isNavidromeAlbumsListCacheStale = navidromeAlbumsListCache.isStale;
