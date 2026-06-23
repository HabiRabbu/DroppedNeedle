import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import type { LocalAlbumSummary, LocalStorageStats } from '$lib/types';
import { createLocalStorageCache } from '$lib/utils/localStorageCache';

type LocalFilesSidebarData = {
	recentAlbums: LocalAlbumSummary[];
	stats: LocalStorageStats | null;
};

const localFilesSidebarCache = createLocalStorageCache<LocalFilesSidebarData>(
	CACHE_KEYS.LOCAL_FILES_SIDEBAR,
	CACHE_TTL.LOCAL_FILES_SIDEBAR
);

export const updateLocalFilesSidebarCacheTTL = localFilesSidebarCache.updateTTL;
