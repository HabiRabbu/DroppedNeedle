import { createMutation, createQuery, queryOptions } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';
import type { QuarantineListResponse } from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

const getQuarantineQueryOptions = () =>
	queryOptions({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: DownloadQueryKeyFactory.quarantine(),
		queryFn: ({ signal }) =>
			api.global.get<QuarantineListResponse>(API.downloads.quarantine(), { signal })
	});

export const getQuarantineQuery = (enabled: () => boolean = () => true) =>
	createQuery(() => ({ ...getQuarantineQueryOptions(), enabled: enabled() }));

export function deleteQuarantineEntry() {
	return createMutation(() => ({
		mutationFn: (id: number) =>
			api.global.delete<{ success: boolean }>(API.downloads.quarantineDelete(id)),
		onSuccess: () => {
			toastStore.show({ message: 'Quarantine entry removed', type: 'success' });
			void invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.quarantine() });
		},
		onError: (err: unknown) =>
			toastStore.show({
				message: err instanceof Error && err.message ? err.message : 'Failed to remove entry',
				type: 'error'
			})
	}));
}
