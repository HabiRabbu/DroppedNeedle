import { createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { LibraryContribution } from '$lib/types';
import { invalidateLibraryCatalog } from '$lib/queries/library/LibraryCatalogInvalidation';
import { LibraryContributionQueryKeyFactory } from './LibraryContributionQueryKeyFactory';

export const getLibraryContributionQuery = (getContributionId: Getter<string>) => {
	const query = createQuery(() => {
		const contributionId = getContributionId();
		return {
			enabled: Boolean(authStore.user?.id && contributionId),
			queryKey: LibraryContributionQueryKeyFactory.detail(authStore.user?.id, contributionId),
			queryFn: async ({ signal }) => {
				const contribution = await api.global.get<LibraryContribution>(
					API.library.contribution(contributionId),
					{
						signal
					}
				);
				if (contribution.state === 'linked') {
					await invalidateLibraryCatalog();
				}
				return contribution;
			},
			refetchInterval: (query: { state: { data?: LibraryContribution } }) =>
				['seeded', 'verifying'].includes(query.state.data?.state ?? '') ? 2_000 : false,
			refetchOnMount: 'always' as const
		};
	});
	return query;
};
