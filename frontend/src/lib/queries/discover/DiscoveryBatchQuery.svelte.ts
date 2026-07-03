import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import { toastStore } from '$lib/stores/toast';
import { createQuery } from '@tanstack/svelte-query';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { DownloadQueryKeyFactory } from '$lib/queries/downloads/DownloadQueryKeyFactory';
import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';
import { DiscoverQueryKeyFactory } from './DiscoverQueryKeyFactory';
import type {
	DiscoveryBatchCreate,
	DiscoveryBatchDetail,
	DiscoveryBatchListResponse,
	DiscoveryBatchRemoveResult
} from '$lib/types';

export const discoveryBatchKeys = {
	list: (userId: string | null | undefined) =>
		[...DiscoverQueryKeyFactory.prefix, userId ?? null, 'batches'] as const
};

export const getDiscoveryBatchesQuery = (getEnabled: () => boolean = () => true) =>
	createQuery(() => ({
		staleTime: 15_000,
		queryKey: discoveryBatchKeys.list(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<DiscoveryBatchListResponse>(API.discoverBatches(), { signal }),
		enabled: getEnabled()
	}));

async function invalidateAfterBatchChange(): Promise<void> {
	await invalidateQueriesWithPersister({
		queryKey: discoveryBatchKeys.list(authStore.user?.id)
	});
	// download (incl. pending-request) and library state both shift when a batch
	// lands or is removed
	await invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.all });
	await invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all });
}

export async function createDiscoveryBatch(
	body: DiscoveryBatchCreate
): Promise<DiscoveryBatchDetail | null> {
	try {
		const created = await api.global.post<DiscoveryBatchDetail>(API.discoverBatches(), body);
		const requested = created.items.filter((i) => i.outcome === 'requested').length;
		const skipped = created.items.length - requested;
		toastStore.show({
			message:
				`${requested} album${requested === 1 ? '' : 's'} requested` +
				(skipped ? ` · ${skipped} already yours or requested` : ''),
			type: 'success'
		});
		await invalidateAfterBatchChange();
		return created;
	} catch (err) {
		toastStore.show({
			message: err instanceof Error ? err.message : "Couldn't create the batch",
			type: 'error'
		});
		return null;
	}
}

export async function removeDiscoveryBatch(
	batchId: string,
	removeAlbums: boolean
): Promise<DiscoveryBatchRemoveResult | null> {
	try {
		const result = await api.global.delete<DiscoveryBatchRemoveResult>(
			API.discoverBatchRemove(batchId, removeAlbums)
		);
		if (removeAlbums) {
			toastStore.show({
				message:
					`Removed ${result.removed_albums} album${result.removed_albums === 1 ? '' : 's'} to the recycle bin` +
					(result.cancelled_requests ? `, cancelled ${result.cancelled_requests} pending` : '') +
					(result.kept ? `, left ${result.kept} untouched` : ''),
				type: 'success'
			});
		} else {
			toastStore.show({ message: 'Batch record removed - albums kept', type: 'success' });
		}
		await invalidateAfterBatchChange();
		return result;
	} catch (err) {
		toastStore.show({
			message: err instanceof Error ? err.message : "Couldn't remove the batch",
			type: 'error'
		});
		return null;
	}
}
