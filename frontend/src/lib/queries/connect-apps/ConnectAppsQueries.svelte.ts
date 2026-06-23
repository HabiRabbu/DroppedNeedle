import { createQuery, queryOptions } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import type { AppPasswordListResponse, ConnectAppsSettings } from '$lib/types';

import { ConnectAppsQueryKeyFactory } from './ConnectAppsQueryKeyFactory';

const settingsQueryOptions = () =>
	queryOptions({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: ConnectAppsQueryKeyFactory.settings(),
		queryFn: ({ signal }) =>
			api.global.get<ConnectAppsSettings>(API.connectApps.settings(), { signal })
	});

export const getConnectAppsSettingsQuery = () => createQuery(() => settingsQueryOptions());

export const getAppPasswordsQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: ConnectAppsQueryKeyFactory.appPasswords(),
		queryFn: ({ signal }) =>
			api.global.get<AppPasswordListResponse>(API.connectApps.appPasswords(), { signal })
	}));
