import { createQuery } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { HomeIntegrationStatus } from '$lib/types';

import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';

export const getIntegrationStatusQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.HOME,
		queryKey: HomeQueryKeyFactory.integrationStatus(authStore.user?.id),
		enabled: Boolean(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<HomeIntegrationStatus>(API.homeIntegrationStatus(), { signal })
	}));
