import { CACHE_KEYS } from '$lib/constants';
import { clearLocalStorageNamespace } from '$lib/utils/localStorageCache';
import { clearNavidromeLocalCaches } from '$lib/utils/navidromeLibraryCache';

// Clear user-dependent localStorage caches that TanStack's user-switch reset does not own.
export function clearUserScopedLocalCaches(): void {
	clearLocalStorageNamespace(CACHE_KEYS.DISCOVER_QUEUE);
	clearLocalStorageNamespace(CACHE_KEYS.TIME_RANGE_OVERVIEW_CACHE);
	clearNavidromeLocalCaches();
}
