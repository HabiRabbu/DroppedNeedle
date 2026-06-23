import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { MusicSource } from '$lib/stores/musicSource';
import type { HomeResponse } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';

export const getHomeQuery = (getSource: Getter<MusicSource>) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.HOME,
		// Read the current user reactively so a switch re-keys + invalidates cleanly.
		queryKey: HomeQueryKeyFactory.home(authStore.user?.id, getSource()),
		queryFn: ({ signal }) =>
			api.global.get<HomeResponse>(API.home(getSource()), {
				signal
			})
	}));
