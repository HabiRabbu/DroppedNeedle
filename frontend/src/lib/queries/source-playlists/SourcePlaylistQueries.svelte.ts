import { createQuery } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { authStore } from '$lib/stores/authStore.svelte';
import type {
	SourcePlaylistCollection,
	SourcePlaylistDetail,
	SourcePlaylistSource
} from '$lib/types';

import { SourcePlaylistQueryKeyFactory } from './SourcePlaylistQueryKeyFactory';

type Getter<T> = () => T;

function listUrl(source: SourcePlaylistSource, limit: number): string {
	switch (source) {
		case 'jellyfin':
			return API.jellyfinLibrary.playlists(limit);
		case 'navidrome':
			return API.navidromeLibrary.playlists(limit);
		case 'plex':
			return API.plexLibrary.playlists(limit);
	}
}

function detailUrl(source: SourcePlaylistSource, playlistId: string): string {
	switch (source) {
		case 'jellyfin':
			return API.jellyfinLibrary.playlistDetail(playlistId);
		case 'navidrome':
			return API.navidromeLibrary.playlistDetail(playlistId);
		case 'plex':
			return API.plexLibrary.playlistDetail(playlistId);
	}
}

export const getSourcePlaylistsQuery = (
	getSource: Getter<SourcePlaylistSource>,
	getLimit: Getter<number> = () => 200,
	getEnabled: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		queryKey: SourcePlaylistQueryKeyFactory.list(authStore.user?.id, getSource(), getLimit()),
		queryFn: ({ signal }) =>
			api.global.get<SourcePlaylistCollection>(listUrl(getSource(), getLimit()), { signal }),
		enabled: getEnabled() && !!authStore.user?.id
	}));

export const getSourcePlaylistDetailQuery = (
	getSource: Getter<SourcePlaylistSource>,
	getPlaylistId: Getter<string>
) =>
	createQuery(() => ({
		queryKey: SourcePlaylistQueryKeyFactory.detail(
			authStore.user?.id,
			getSource(),
			getPlaylistId()
		),
		queryFn: ({ signal }) =>
			api.global.get<SourcePlaylistDetail>(detailUrl(getSource(), getPlaylistId()), { signal }),
		enabled: !!authStore.user?.id && !!getPlaylistId()
	}));
