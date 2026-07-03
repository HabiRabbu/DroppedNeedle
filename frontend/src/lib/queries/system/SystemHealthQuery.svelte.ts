import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import type { SystemHealthResponse } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import { SystemQueryKeyFactory } from './SystemQueryKeyFactory';

/** Which external services are currently degraded - drives the header health dot.
 * Polls on a slow cadence (a service outage is minutes-scale, not seconds) and on
 * window focus so a returning user sees current state. Not user-specific. */
export const getSystemHealthQuery = () =>
	createQuery(() => ({
		queryKey: SystemQueryKeyFactory.health(),
		queryFn: ({ signal }) => api.global.get<SystemHealthResponse>(API.system.health(), { signal }),
		refetchInterval: 60_000,
		refetchOnWindowFocus: true,
		staleTime: 30_000
	}));
