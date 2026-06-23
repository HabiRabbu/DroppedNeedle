import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { authStore } from '$lib/stores/authStore.svelte';
import { ConnectionsQueryKeyFactory } from './ConnectionsQueryKeyFactory';
import { CONNECTIONS_ENDPOINTS } from './endpoints';
import type { ConnectionsResponse } from './types';

export const getConnectionsQuery = () =>
	createQuery(() => ({
		queryKey: ConnectionsQueryKeyFactory.list(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<ConnectionsResponse>(CONNECTIONS_ENDPOINTS.list, { signal })
	}));
