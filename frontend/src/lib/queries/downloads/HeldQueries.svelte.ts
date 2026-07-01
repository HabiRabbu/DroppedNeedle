import { createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import type { HeldListResponse } from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

// Tracks held for an "import anyway" review. Two callers: the Downloads dashboard (no
// filter, cross-album triage) and the album page (scoped to one release group). Keyed under
// tasks() so a download mutation's invalidateTasks() refreshes it too. A slow poll keeps the
// dashboard fresh without the 5s task cadence (held items change only on a verify-fail).
export const getHeldImportsQuery = (
	getMbid: Getter<string | undefined> = () => undefined,
	getEnabled: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		enabled: getEnabled(),
		queryKey: DownloadQueryKeyFactory.held(getMbid()),
		refetchInterval: 10000,
		queryFn: ({ signal }) =>
			api.global.get<HeldListResponse>(API.downloads.held(getMbid()), { signal })
	}));
