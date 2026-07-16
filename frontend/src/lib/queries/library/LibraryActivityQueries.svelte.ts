import { createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type { LibraryActivityResponse } from './LibraryOperationsTypes';

export const getLibraryActivityQueryOptions = (userId: string | undefined) =>
	queryOptions({
		queryKey: LibraryQueryKeyFactory.activity(userId),
		queryFn: ({ signal }) =>
			api.global.get<LibraryActivityResponse>(API.library.activity(), { signal }),
		staleTime: 2_000
	});

export const getLibraryActivityQuery = (getUserId: Getter<string | undefined>) =>
	createQuery(() => ({
		...getLibraryActivityQueryOptions(getUserId()),
		enabled: Boolean(getUserId())
	}));
