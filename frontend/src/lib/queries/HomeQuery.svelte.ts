import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { HomeResponse } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';

function sectionCount(d: HomeResponse | null | undefined): number {
	if (!d) return 0;
	const sections = [
		d.recently_added,
		d.library_artists,
		d.library_albums,
		d.trending_artists,
		d.popular_albums,
		d.recently_played,
		d.genre_list,
		d.favorite_artists,
		d.your_top_albums,
		d.weekly_exploration
	];
	return sections.filter((s) => s != null).length;
}

// Server-side SWR pairs with this client guard: while the backend is still
// building (a thin, `refreshing` response), keep showing the richer copy we
// already have instead of dropping sections and re-growing them.
async function fetchHome(
	userId: string | null | undefined,
	signal?: AbortSignal
): Promise<HomeResponse> {
	const fresh = await api.global.get<HomeResponse>(API.home(), { signal });
	if (fresh.refreshing) {
		const { queryClient } = await import('$lib/queries/QueryClient');
		const prev = queryClient.getQueryData<HomeResponse>(HomeQueryKeyFactory.home(userId));
		if (prev && sectionCount(prev) > sectionCount(fresh)) {
			return { ...prev, refreshing: true };
		}
	}
	return fresh;
}

export const getHomeQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.HOME,
		// Read the current user reactively so a switch re-keys + invalidates cleanly.
		queryKey: HomeQueryKeyFactory.home(authStore.user?.id),
		queryFn: ({ signal }) => fetchHome(authStore.user?.id, signal),
		// while the backend streams the full build in, poll until it lands
		refetchInterval: (query: { state: { data?: HomeResponse | undefined } }) =>
			query.state.data?.refreshing ? 3000 : false
	}));
