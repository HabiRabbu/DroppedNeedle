import { writable, get } from 'svelte/store';
import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import { createLocalStorageCache } from '$lib/utils/localStorageCache';
import { api } from '$lib/api/client';

interface LibraryState {
	mbidSet: Set<string>;
	requestedSet: Set<string>;
	loading: boolean;
	lastUpdated: number | null;
	initialized: boolean;
}

const initialState: LibraryState = {
	mbidSet: new Set(),
	requestedSet: new Set(),
	loading: false,
	lastUpdated: null,
	initialized: false
};

type LibraryCacheData = {
	mbids: string[];
	requested: string[];
};

function createLibraryStore() {
	const { subscribe, update } = writable<LibraryState>(initialState);
	const cache = createLocalStorageCache<LibraryCacheData | string[]>(
		CACHE_KEYS.LIBRARY_MBIDS,
		CACHE_TTL.LIBRARY
	);

	function normalizeCachedData(data: LibraryCacheData | string[]): LibraryCacheData {
		if (Array.isArray(data)) {
			return { mbids: data, requested: [] };
		}
		return {
			mbids: data.mbids ?? [],
			requested: data.requested ?? []
		};
	}

	function persistState(mbidSet: Set<string>, requestedSet: Set<string>) {
		cache.set({
			mbids: [...mbidSet],
			requested: [...requestedSet]
		});
	}

	async function initialize() {
		const state = get({ subscribe });
		if (state.initialized || state.loading) return;

		const cached = cache.get();
		if (cached) {
			const normalized = normalizeCachedData(cached.data);
			const mbids = normalized.mbids.map((m) => m.toLowerCase());
			const requested = normalized.requested.map((m) => m.toLowerCase());

			if (mbids.length === 0 && requested.length === 0) {
				await fetchLibraryMbids(false);
				return;
			}

			update((s) => ({
				...s,
				mbidSet: new Set(mbids),
				requestedSet: new Set(requested),
				lastUpdated: cached.timestamp,
				initialized: true
			}));

			const BACKGROUND_REFRESH_TTL = 30_000;
			if (Date.now() - cached.timestamp > BACKGROUND_REFRESH_TTL) {
				fetchLibraryMbids(true);
			}
		} else {
			await fetchLibraryMbids(false);
		}
	}

	async function fetchLibraryMbids(background = false) {
		if (!background) {
			update((s) => ({ ...s, loading: true }));
		}

		try {
			const data = await api.global.get<{
				mbids?: string[];
				requested_mbids?: string[];
			}>('/api/v1/library/mbids');
			const mbids: string[] = (data.mbids || []).map((m: string) => m.toLowerCase());
			const requested: string[] = (data.requested_mbids || []).map((m: string) => m.toLowerCase());

			update((s) => ({
				...s,
				mbidSet: new Set(mbids),
				requestedSet: new Set(requested),
				loading: false,
				lastUpdated: Date.now(),
				initialized: true
			}));

			cache.set({ mbids, requested });
		} catch {
			if (!background) {
				update((s) => ({ ...s, loading: false, initialized: true }));
			}
		}
	}

	function isInLibrary(mbid: string | null | undefined): boolean {
		if (!mbid) return false;
		const state = get({ subscribe });
		return state.mbidSet.has(mbid.toLowerCase());
	}

	function addMbid(mbid: string) {
		update((s) => {
			const newSet = new Set(s.mbidSet);
			newSet.add(mbid.toLowerCase());
			const newRequested = new Set(s.requestedSet);
			newRequested.delete(mbid.toLowerCase());
			persistState(newSet, newRequested);
			return { ...s, mbidSet: newSet, requestedSet: newRequested };
		});
	}

	function removeMbid(mbid: string) {
		update((s) => {
			const newSet = new Set(s.mbidSet);
			newSet.delete(mbid.toLowerCase());
			const newRequested = new Set(s.requestedSet);
			newRequested.delete(mbid.toLowerCase());
			persistState(newSet, newRequested);
			return { ...s, mbidSet: newSet, requestedSet: newRequested };
		});
	}

	function addRequested(mbid: string) {
		update((s) => {
			if (s.mbidSet.has(mbid.toLowerCase())) {
				return s;
			}
			const lower = mbid.toLowerCase();
			const newRequested = new Set(s.requestedSet);
			newRequested.add(lower);
			persistState(s.mbidSet, newRequested);
			return { ...s, requestedSet: newRequested };
		});
	}

	function isRequested(mbid: string | null | undefined): boolean {
		if (!mbid) return false;
		const lower = mbid.toLowerCase();
		const state = get({ subscribe });
		return state.requestedSet.has(lower) && !state.mbidSet.has(lower);
	}

	async function refresh() {
		await fetchLibraryMbids(false);
	}

	async function refreshIfStale(ttlMs: number) {
		const state = get({ subscribe });
		if (!state.initialized) {
			await initialize();
			return;
		}
		if (state.lastUpdated && Date.now() - state.lastUpdated < ttlMs) return;
		await fetchLibraryMbids(true);
	}

	return {
		subscribe,
		initialize,
		refresh,
		refreshIfStale,
		isInLibrary,
		addMbid,
		removeMbid,
		isRequested,
		addRequested,
		updateCacheTTL: cache.updateTTL
	};
}

export const libraryStore = createLibraryStore();
