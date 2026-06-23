import { createMutation, createQuery, queryOptions } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import type { PickResponse, SearchAlbumResponse, SearchJobView } from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

interface AlbumSearchInput {
	artist_name: string;
	album_title: string;
	year?: number | null;
	track_count?: number | null;
	release_group_mbid?: string | null;
}

export const getSearchJobQueryOptions = (jobId: string) =>
	queryOptions({
		staleTime: 0,
		queryKey: DownloadQueryKeyFactory.searchJob(jobId),
		queryFn: ({ signal }) =>
			api.global.get<SearchJobView>(API.downloads.searchJob(jobId), { signal })
	});

export const getSearchJobQuery = (jobId: () => string) =>
	createQuery(() => getSearchJobQueryOptions(jobId()));

export function startAlbumSearch() {
	return createMutation(() => ({
		mutationFn: (input: AlbumSearchInput) =>
			api.global.post<SearchAlbumResponse>(API.downloads.searchAlbum(), input)
	}));
}

export function pickSearchCandidate() {
	return createMutation(() => ({
		mutationFn: (input: { jobId: string; candidate_index: number }) =>
			api.global.post<PickResponse>(API.downloads.pick(input.jobId), {
				candidate_index: input.candidate_index
			}),
		onSuccess: (_data: PickResponse, input: { jobId: string; candidate_index: number }) =>
			invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.searchJob(input.jobId) })
	}));
}

export function cancelSearch() {
	return createMutation(() => ({
		mutationFn: (jobId: string) =>
			api.global.post<{ status: string; message: string }>(API.downloads.cancelSearch(jobId), {}),
		onSuccess: (_data: { status: string; message: string }, jobId: string) =>
			invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.searchJob(jobId) })
	}));
}
