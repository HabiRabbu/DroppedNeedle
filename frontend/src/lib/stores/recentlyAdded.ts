import { writable, get } from 'svelte/store';
import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import { createLocalStorageCache } from '$lib/utils/localStorageCache';
import { api } from '$lib/api/client';

interface LibraryArtist {
	name: string;
	mbid: string;
	album_count: number;
	date_added: string | null;
}

interface LibraryAlbum {
	album: string;
	artist: string;
	artist_mbid: string | null;
	musicbrainz_id: string | null;
	year: number | null;
	cover_url: string | null;
	date_added: number | null;
}

interface RecentlyAddedData {
	artists: LibraryArtist[];
	albums: LibraryAlbum[];
}

interface RecentlyAddedState {
	data: RecentlyAddedData | null;
	loading: boolean;
	lastUpdated: number | null;
	initialized: boolean;
}

const cache = createLocalStorageCache<RecentlyAddedData>(
	CACHE_KEYS.RECENTLY_ADDED,
	CACHE_TTL.RECENTLY_ADDED
);

function getInitialState(): RecentlyAddedState {
	const cached = cache.get();
	if (cached?.data) {
		return {
			data: cached.data,
			loading: false,
			lastUpdated: cached.timestamp,
			initialized: true
		};
	}
	return {
		data: null,
		loading: false,
		lastUpdated: null,
		initialized: false
	};
}

function createRecentlyAddedStore() {
	const { subscribe, update } = writable<RecentlyAddedState>(getInitialState());

	async function initialize() {
		const state = get({ subscribe });
		if (state.loading) return;

		if (state.initialized && state.data) {
			if (state.lastUpdated && cache.isStale(state.lastUpdated)) {
				fetchRecentlyAdded(true);
			}
			return;
		}

		await fetchRecentlyAdded(false);
	}

	async function fetchRecentlyAdded(background = false) {
		if (!background) {
			update((s) => ({ ...s, loading: true }));
		}

		try {
			const data = await api.global.get<RecentlyAddedData>('/api/v1/library/recently-added');

			update((s) => ({
				...s,
				data,
				loading: false,
				lastUpdated: Date.now(),
				initialized: true
			}));

			cache.set(data);
		} catch (_e) {
			if (!background) {
				update((s) => ({ ...s, loading: false, initialized: true }));
			}
		}
	}

	function isStale(): boolean {
		const state = get({ subscribe });
		if (!state.lastUpdated) return true;
		return cache.isStale(state.lastUpdated);
	}

	async function refresh() {
		await fetchRecentlyAdded(false);
	}

	async function refreshInBackground() {
		await fetchRecentlyAdded(true);
	}

	return {
		subscribe,
		initialize,
		refresh,
		refreshInBackground,
		isStale,
		updateCacheTTL: cache.updateTTL
	};
}

export const recentlyAddedStore = createRecentlyAddedStore();
