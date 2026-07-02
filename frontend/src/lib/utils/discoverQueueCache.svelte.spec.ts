import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import {
	getQueueCachedData,
	removeQueueCachedData,
	setQueueCachedData,
	subscribeQueueCacheChanges,
	updateDiscoverQueueCacheTTL
} from './discoverQueueCache';

const USER_A = 'user-a';
const USER_B = 'user-b';

describe('discoverQueueCache', () => {
	beforeEach(() => {
		localStorage.clear();
		updateDiscoverQueueCacheTTL(CACHE_TTL.DISCOVER_QUEUE);
		vi.restoreAllMocks();
	});

	it('stores and retrieves queue items with enrichment payload', () => {
		expect.assertions(3);
		setQueueCachedData(
			{
				items: [
					{
						release_group_mbid: 'rg-1',
						album_name: 'Album 1',
						artist_name: 'Artist 1',
						artist_mbid: 'artist-1',
						cover_url: null,
						recommendation_reason: 'reason',
						is_wildcard: false,
						in_library: false,
						enrichment: {
							artist_mbid: 'artist-1',
							release_date: '1970-01-01',
							country: 'GB',
							tags: ['prog rock'],
							youtube_url: null,
							youtube_search_url: 'https://youtube.example',
							youtube_search_available: true,
							artist_description: 'desc',
							listen_count: 10
						}
					}
				],
				currentIndex: 0,
				queueId: 'queue-1'
			},
			USER_A,
			'listenbrainz'
		);

		const cached = getQueueCachedData(USER_A, 'listenbrainz');
		expect(cached).not.toBeNull();
		expect(cached?.data.items[0].enrichment?.release_date).toBe('1970-01-01');
		expect(cached?.data.queueId).toBe('queue-1');
	});

	it('invalidates stale queue cache entries on read', () => {
		expect.assertions(2);
		updateDiscoverQueueCacheTTL(10);
		vi.spyOn(Date, 'now').mockReturnValue(1000);
		setQueueCachedData(
			{
				items: [],
				currentIndex: 0,
				queueId: 'queue-2'
			},
			USER_A,
			'lastfm'
		);

		vi.spyOn(Date, 'now').mockReturnValue(1200);
		const cached = getQueueCachedData(USER_A, 'lastfm');
		expect(cached).toBeNull();
		expect(localStorage.getItem(`${CACHE_KEYS.DISCOVER_QUEUE}_${USER_A}:lastfm`)).toBeNull();
	});

	it('emits cache change events for same-tab updates', () => {
		expect.assertions(2);
		const sources: Array<string | undefined> = [];
		const unsubscribe = subscribeQueueCacheChanges((source) => {
			sources.push(source);
		});

		setQueueCachedData(
			{
				items: [],
				currentIndex: 0,
				queueId: 'queue-3'
			},
			USER_A,
			'listenbrainz'
		);
		removeQueueCachedData(USER_A, 'listenbrainz');
		unsubscribe();

		expect(sources).toHaveLength(2);
		expect(sources).toEqual(['listenbrainz', 'listenbrainz']);
	});

	it('isolates cache entries per user (no cross-user leak)', () => {
		expect.assertions(3);
		setQueueCachedData({ items: [], currentIndex: 0, queueId: 'queue-a' }, USER_A, 'listenbrainz');
		setQueueCachedData({ items: [], currentIndex: 0, queueId: 'queue-b' }, USER_B, 'listenbrainz');

		expect(getQueueCachedData(USER_A, 'listenbrainz')?.data.queueId).toBe('queue-a');
		expect(getQueueCachedData(USER_B, 'listenbrainz')?.data.queueId).toBe('queue-b');
		// User B has no entry for a source only user A wrote.
		expect(getQueueCachedData(USER_B, 'lastfm')).toBeNull();
	});
});
