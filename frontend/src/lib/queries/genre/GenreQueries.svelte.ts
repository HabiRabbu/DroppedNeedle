import { createInfiniteQuery } from '@tanstack/svelte-query';
import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { GenreDetailResponse } from '$lib/types';
import { GenreQueryKeyFactory } from './GenreQueryKeyFactory';

type Getter<T> = () => T;
const PAGE_SIZE = 50;

export const getGenreDetailQuery = (getGenre: Getter<string>) =>
	createInfiniteQuery(() => ({
		staleTime: CACHE_TTL.GENRE_DETAIL,
		queryKey: GenreQueryKeyFactory.artistPages(authStore.user?.id, getGenre()),
		initialPageParam: 0,
		enabled: getGenre().trim().length > 0,
		queryFn: ({ pageParam = 0, signal }) =>
			api.global.get<GenreDetailResponse>(API.homeGenre(getGenre(), PAGE_SIZE, pageParam, 0), {
				signal
			}),
		getNextPageParam: (lastPage, allPages) =>
			lastPage.popular?.has_more_artists ? allPages.length * PAGE_SIZE : undefined
	}));

export const getGenreAlbumPagesQuery = (getGenre: Getter<string>, getEnabled: Getter<boolean>) =>
	createInfiniteQuery(() => ({
		staleTime: CACHE_TTL.GENRE_DETAIL,
		queryKey: GenreQueryKeyFactory.albumPages(authStore.user?.id, getGenre()),
		initialPageParam: PAGE_SIZE,
		enabled: getGenre().trim().length > 0 && getEnabled(),
		queryFn: ({ pageParam = PAGE_SIZE, signal }) =>
			api.global.get<GenreDetailResponse>(API.homeGenre(getGenre(), PAGE_SIZE, 0, pageParam), {
				signal
			}),
		getNextPageParam: (lastPage, allPages) =>
			lastPage.popular?.has_more_albums ? PAGE_SIZE + allPages.length * PAGE_SIZE : undefined
	}));
