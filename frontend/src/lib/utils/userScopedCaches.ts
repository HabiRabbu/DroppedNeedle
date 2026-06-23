import { CACHE_KEYS } from '$lib/constants';
import { clearLocalStorageNamespace } from '$lib/utils/localStorageCache';

// Clears the localStorage caches resetQueryCacheForUserSwitch doesn't cover (discover queue +
// time-range overview), so personalized data can't leak across users sharing a browser.
export function clearUserScopedLocalCaches(): void {
	clearLocalStorageNamespace(CACHE_KEYS.DISCOVER_QUEUE);
	clearLocalStorageNamespace(CACHE_KEYS.TIME_RANGE_OVERVIEW_CACHE);
}
