import { createQuery } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';

import { PluginQueryKeyFactory } from './PluginQueryKeyFactory';
import type { PluginListResponse } from './types';

type Getter<T> = () => T;

// Admin-only: the Settings -> Plugins roster.
export const getPluginsQuery = (getEnabled: Getter<boolean> = () => true) =>
	createQuery(() => ({
		queryKey: PluginQueryKeyFactory.list(),
		queryFn: ({ signal }) => api.global.get<PluginListResponse>(API.plugins.list(), { signal }),
		enabled: getEnabled()
	}));
