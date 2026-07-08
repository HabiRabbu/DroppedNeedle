import { createQuery, queryOptions } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type {
	AdminAppPasswordListResponse,
	AppPasswordListResponse,
	ConnectAppsSettings
} from '$lib/types';

import { ConnectAppsQueryKeyFactory } from './ConnectAppsQueryKeyFactory';

const settingsQueryOptions = () =>
	queryOptions({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: ConnectAppsQueryKeyFactory.settings(),
		queryFn: ({ signal }) =>
			api.global.get<ConnectAppsSettings>(API.connectApps.settings(), { signal })
	});

export const getConnectAppsSettingsQuery = () => createQuery(() => settingsQueryOptions());

// app-passwords are always the current user's own; the userId keys the cache per user.
// `enabled` gates the fetch until auth resolves so nothing is ever written under an
// empty-id key (matches the user-scoped query pattern elsewhere).
export const getAppPasswordsQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		enabled: !!authStore.user?.id,
		queryKey: ConnectAppsQueryKeyFactory.appPasswords(authStore.user?.id ?? ''),
		queryFn: ({ signal }) =>
			api.global.get<AppPasswordListResponse>(API.connectApps.appPasswords(), { signal })
	}));

// admin oversight: every user's active app-passwords (metadata only, no secrets)
export const getAdminAppPasswordsQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.LIBRARY_NATIVE,
		queryKey: ConnectAppsQueryKeyFactory.adminAppPasswords(),
		queryFn: ({ signal }) =>
			api.global.get<AdminAppPasswordListResponse>(API.connectApps.adminAppPasswords(), { signal })
	}));
