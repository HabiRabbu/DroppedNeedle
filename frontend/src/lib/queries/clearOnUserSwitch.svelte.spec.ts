import { beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/svelte-query';
import { CACHE_KEYS } from '$lib/constants';
import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';
import { setQueueCachedData } from '$lib/utils/discoverQueueCache';
import { overviewCacheSuffix } from '$lib/utils/timeRangeCache';
import { clearUserScopedLocalCaches } from '$lib/utils/userScopedCaches';

// A switch must drop both the user-keyed TanStack home cache and the localStorage caches the
// query-cache reset misses; asserts the two mechanisms in isolation, not the logout() orchestration.
describe('clear-on-user-switch (AMU-5)', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('queryClient.clear() drops the user-keyed home entry', () => {
		const qc = new QueryClient();
		const key = HomeQueryKeyFactory.home('user-a', 'listenbrainz');
		qc.setQueryData(key, { greeting: 'hi A' });
		expect(qc.getQueryData(key)).toBeDefined();

		qc.clear();
		expect(qc.getQueryData(key)).toBeUndefined();
	});

	it('clearUserScopedLocalCaches() removes the prior user discover-queue + time-range entries', () => {
		setQueueCachedData({ items: [], currentIndex: 0, queueId: 'q-a' }, 'user-a', 'listenbrainz');
		const queueKey = `${CACHE_KEYS.DISCOVER_QUEUE}_user-a:listenbrainz`;
		const trKey = `${CACHE_KEYS.TIME_RANGE_OVERVIEW_CACHE}_${overviewCacheSuffix(
			'user-a',
			'album',
			'listenbrainz',
			'/api/v1/home/your-top/albums'
		)}`;
		localStorage.setItem(trKey, JSON.stringify({ data: {}, timestamp: Date.now() }));

		expect(localStorage.getItem(queueKey)).not.toBeNull();
		expect(localStorage.getItem(trKey)).not.toBeNull();

		clearUserScopedLocalCaches();

		expect(localStorage.getItem(queueKey)).toBeNull();
		expect(localStorage.getItem(trKey)).toBeNull();
	});
});
