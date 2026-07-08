import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { authStore } from '$lib/stores/authStore.svelte';
import type { AppPasswordCreateResponse, ConnectAppsSettings } from '$lib/types';

import { ConnectAppsQueryKeyFactory } from './ConnectAppsQueryKeyFactory';

const invalidateOwnAppPasswords = () =>
	invalidateQueriesWithPersister({
		queryKey: ConnectAppsQueryKeyFactory.appPasswords(authStore.user?.id ?? '')
	});

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
		onSuccess: invalidateOwnAppPasswords
	}));
}

export function revokeAppPassword() {
	return createMutation(() => ({
		mutationFn: (id: string) => api.global.delete<void>(API.connectApps.appPassword(id)),
		onSuccess: invalidateOwnAppPasswords
	}));
}

// admin revokes any user's app-password; pass the owning user_id so we can also
// refresh the admin's OWN profile list when they revoke one of their own (same
// browser). Another user's list can't be invalidated from here - their client
// refreshes on next load; server-side auth dies immediately regardless.
export function adminRevokeAppPassword() {
	return createMutation(() => ({
		mutationFn: (vars: { id: string; userId: string }) =>
			api.global.delete<void>(API.connectApps.adminAppPassword(vars.id)),
		onSuccess: (_data: void, vars: { id: string; userId: string }) => {
			invalidateQueriesWithPersister({
				queryKey: ConnectAppsQueryKeyFactory.adminAppPasswords()
			});
			if (vars.userId === authStore.user?.id) invalidateOwnAppPasswords();
		}
	}));
}
