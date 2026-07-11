import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { SectionPrefsResponse, SectionPrefsUpdate } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import { HomeQueryKeyFactory } from '$lib/queries/HomeQueryKeyFactory';
import { DiscoverQueryKeyFactory } from '$lib/queries/discover/DiscoverQueryKeyFactory';
import {
	invalidateQueriesWithPersister,
	setQueryDataWithPersister
} from '$lib/queries/QueryClient';
import { SectionPrefsQueryKeyFactory } from './SectionPrefsQueryKeyFactory';

export const getSectionPrefsQuery = () =>
	createQuery(() => ({
		staleTime: 60_000,
		queryKey: SectionPrefsQueryKeyFactory.prefs(authStore.user?.id),
		queryFn: ({ signal }) => api.global.get<SectionPrefsResponse>(API.me.sectionPrefs(), { signal })
	}));

/** Save one page's toggles; refreshes the prefs cache and invalidates the page data. */
export async function saveSectionPrefs(update: SectionPrefsUpdate): Promise<void> {
	const saved = await api.global.put<SectionPrefsResponse>(API.me.sectionPrefs(), update);
	const userId = authStore.user?.id;
	await setQueryDataWithPersister<SectionPrefsResponse>(
		SectionPrefsQueryKeyFactory.prefs(userId),
		(prev) => ({
			pages: { ...(prev?.pages ?? {}), ...saved.pages }
		})
	);
	// the home/discover responses are filtered server-side, so their caches are stale
	// now; sidebar prefs are client-only chrome read straight from the prefs cache
	if (update.page === 'home') {
		await invalidateQueriesWithPersister({ queryKey: HomeQueryKeyFactory.prefix });
	} else if (update.page === 'discover') {
		await invalidateQueriesWithPersister({ queryKey: DiscoverQueryKeyFactory.prefix });
	}
}
