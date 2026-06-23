import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import type { AppPasswordCreateResponse, ConnectAppsSettings } from '$lib/types';

import { ConnectAppsQueryKeyFactory } from './ConnectAppsQueryKeyFactory';

export function saveConnectAppsSettings() {
	return createMutation(() => ({
		mutationFn: (settings: ConnectAppsSettings) =>
			api.global.put<ConnectAppsSettings>(API.connectApps.settings(), settings),
		onSuccess: () =>
			invalidateQueriesWithPersister({ queryKey: ConnectAppsQueryKeyFactory.settings() })
	}));
}

export function createAppPassword() {
	return createMutation(() => ({
		mutationFn: (name: string) =>
			api.global.post<AppPasswordCreateResponse>(API.connectApps.appPasswords(), { name }),
		// returned secret stays in component state for the one-time reveal, never cached
		onSuccess: () =>
			invalidateQueriesWithPersister({ queryKey: ConnectAppsQueryKeyFactory.appPasswords() })
	}));
}

export function revokeAppPassword() {
	return createMutation(() => ({
		mutationFn: (id: string) => api.global.delete<void>(API.connectApps.appPassword(id)),
		onSuccess: () =>
			invalidateQueriesWithPersister({ queryKey: ConnectAppsQueryKeyFactory.appPasswords() })
	}));
}
