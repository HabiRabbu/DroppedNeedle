let _CACHE_TTL_MS = 5 * 60 * 1000;

export function updateDiscoveryCacheTTL(ttlMs: number): void {
	_CACHE_TTL_MS = ttlMs;
}
