import { createMutation, createQuery, queryOptions } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { HomeQueryKeyFactory } from '$lib/queries/HomeQueryKeyFactory';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import type { DownloadClientConfig, DownloadClientStatus, TestConnectionResult } from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

const getDownloadClientConfigQueryOptions = () =>
	queryOptions({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: DownloadQueryKeyFactory.clientConfig(),
		queryFn: ({ signal }) =>
			api.global.get<DownloadClientConfig>(API.downloadClient.config(), { signal })
	});

export const getDownloadClientConfigQuery = () =>
	createQuery(() => getDownloadClientConfigQueryOptions());

const getDownloadClientStatusQueryOptions = () =>
	queryOptions({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: DownloadQueryKeyFactory.clientStatus(),
		queryFn: ({ signal }) =>
			api.global.get<DownloadClientStatus>(API.downloadClient.status(), { signal })
	});

export const getDownloadClientStatusQuery = () =>
	createQuery(() => getDownloadClientStatusQueryOptions());

export function saveDownloadClientConfig() {
	return createMutation(() => ({
		mutationFn: (config: DownloadClientConfig) =>
			api.global.put<DownloadClientConfig>(API.downloadClient.config(), config),
		onSuccess: async () => {
			await invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.clientConfig() });
			await invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.clientStatus() });
			// Home reads integration_status.download_client; invalidate or its
			// "Configure Download Client" prompt lingers until the cache expires
			await invalidateQueriesWithPersister({ queryKey: HomeQueryKeyFactory.prefix });
		}
	}));
}

export function testDownloadClient() {
	return createMutation(() => ({
		mutationFn: (config: DownloadClientConfig) =>
			api.global.post<TestConnectionResult>(API.downloadClient.test(), config)
	}));
}
