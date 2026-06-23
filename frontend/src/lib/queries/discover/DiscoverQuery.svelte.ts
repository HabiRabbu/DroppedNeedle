import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type { MusicSource } from '$lib/stores/musicSource';
import type { DiscoverResponse, HomeSection, PlaylistSuggestionsResponse } from '$lib/types';
import { createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { DiscoverQueryKeyFactory } from './DiscoverQueryKeyFactory';

export const getDiscoverQueryOptions = (userId: string | null | undefined, source: MusicSource) =>
	queryOptions({
		staleTime: CACHE_TTL.DISCOVER,
		queryKey: DiscoverQueryKeyFactory.discover(userId, source),
		queryFn: ({ signal }) =>
			api.global.get<DiscoverResponse>(API.discover(source), {
				signal
			})
	});

export const getDiscoverQuery = (getSource: Getter<MusicSource>) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.DISCOVER,
		queryKey: DiscoverQueryKeyFactory.discover(authStore.user?.id, getSource()),
		queryFn: ({ signal }) =>
			api.global.get<DiscoverResponse>(API.discover(getSource()), {
				signal
			}),
		refetchInterval: (query: { state: { data?: DiscoverResponse | undefined } }) =>
			query.state.data?.refreshing ? 3000 : false
	}));

export const getRadioQuery = (
	getParams: Getter<{ seedType: string; seedId: string; source: MusicSource }>
) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.DISCOVER,
		queryKey: DiscoverQueryKeyFactory.radio(
			authStore.user?.id,
			getParams().seedType,
			getParams().seedId,
			getParams().source
		),
		queryFn: ({ signal }) =>
			api.global.post<HomeSection>(
				API.discoverRadio(),
				{
					seed_type: getParams().seedType,
					seed_id: getParams().seedId,
					source: getParams().source
				},
				{ signal }
			),
		enabled: !!getParams().seedId
	}));

export const getPlaylistSuggestionsQuery = (
	getParams: Getter<{
		playlistId: string;
		count?: number;
		source?: MusicSource | null;
		enabled?: boolean;
	}>
) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.DISCOVER,
		queryKey: DiscoverQueryKeyFactory.playlistSuggestions(
			authStore.user?.id,
			getParams().playlistId,
			getParams().source
		),
		queryFn: ({ signal }) =>
			api.global.post<PlaylistSuggestionsResponse>(
				API.discoverPlaylistSuggestions(),
				{
					playlist_id: getParams().playlistId,
					count: getParams().count ?? 15,
					source: getParams().source ?? undefined
				},
				{ signal }
			),
		enabled: (getParams().enabled ?? true) && !!getParams().playlistId
	}));
