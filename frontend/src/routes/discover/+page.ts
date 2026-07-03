import { getDiscoverQueryOptions } from '$lib/queries/discover/DiscoverQuery.svelte';
import { queryClient } from '$lib/queries/QueryClient';
import { authStore } from '$lib/stores/authStore.svelte';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => {
	await queryClient.prefetchQuery(getDiscoverQueryOptions(authStore.user?.id));

	return {};
};
