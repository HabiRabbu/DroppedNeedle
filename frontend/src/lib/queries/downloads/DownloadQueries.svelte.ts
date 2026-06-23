import { createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import type { DownloadListResponse } from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';
import { hasActiveTask } from './downloadStatus';

// one query fetches the whole queue; tabs + counts are derived client-side (backend list has no `counts`). polls every 5s; items also subscribe to SSE for live progress
export const getDownloadsQueryOptions = () =>
	queryOptions({
		staleTime: 0,
		refetchInterval: 5000,
		queryKey: DownloadQueryKeyFactory.tasks(),
		queryFn: ({ signal }) =>
			api.global.get<DownloadListResponse>(API.downloads.list(undefined, 1, 100), { signal })
	});

export const getDownloadsQuery = () => createQuery(() => getDownloadsQueryOptions());

// album-scoped: just this release group's tasks (album + per-track). Cheap (indexed
// on release_group_mbid), and only polls while a task is in flight - it stops itself
// when everything reaches a terminal state. Used by the album page for live progress.
export const getAlbumDownloadsQuery = (
	getMbid: Getter<string>,
	getEnabled: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		staleTime: 0,
		enabled: getEnabled() && !!getMbid(),
		queryKey: DownloadQueryKeyFactory.albumTasks(getMbid()),
		queryFn: ({ signal }) =>
			api.global.get<DownloadListResponse>(API.downloads.list(undefined, 1, 100, getMbid()), {
				signal
			}),
		refetchInterval: (query: { state: { data?: DownloadListResponse | undefined } }) =>
			hasActiveTask(query.state.data?.items ?? []) ? 2500 : false
	}));
