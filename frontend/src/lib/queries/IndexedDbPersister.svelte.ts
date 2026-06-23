import type { AsyncStorage, PersistedQuery } from '@tanstack/svelte-query-persist-client';
import { clear, del, entries, get, set } from 'idb-keyval';

/**
 * Wipe every persisted query from IndexedDB on a user switch (AMU-5): the
 * per-query entries written by {@link createIDBStorage}. idb-keyval's default
 * store is used only by this persister (verified), so a blanket `clear()` is safe
 * and cannot drop unrelated app data.
 */
export async function clearPersistedQueryCache(): Promise<void> {
	await clear();
}

export function createIDBStorage(): AsyncStorage<PersistedQuery> {
	return {
		getItem: async (key: string) => {
			const val = await get<PersistedQuery>(key);
			return val;
		},
		setItem: async (key: string, value: PersistedQuery) => {
			// In some cases, a svelte state proxy value appears in the query state, which cannot be stored in IndexedDB.
			// To work around this, we can snapshot the value before storing it.
			try {
				await set(key, $state.snapshot(value));
			} catch (e) {
				console.error('Failed to set item in IndexedDB', key, value, e);
				throw e;
			}
		},
		removeItem: async (key: string) => {
			await del(key);
		},
		entries: async () => {
			return await entries();
		}
	};
}
