import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { authStore } from '$lib/stores/authStore.svelte';
import { ScrobblePreferencesQueryKeyFactory } from './ScrobblePreferencesQueryKeyFactory';
import { SCROBBLE_PREFERENCES_ENDPOINTS } from './endpoints';
import type { ScrobblePreferences } from './types';

export const getScrobblePreferencesQuery = () =>
	createQuery(() => ({
		queryKey: ScrobblePreferencesQueryKeyFactory.get(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<ScrobblePreferences>(SCROBBLE_PREFERENCES_ENDPOINTS.get, { signal })
	}));
