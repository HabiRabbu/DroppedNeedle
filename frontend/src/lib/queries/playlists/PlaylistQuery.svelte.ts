import { fetchPlaylists, fetchPlaylist } from '$lib/api/playlists';
import { createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { authStore } from '$lib/stores/authStore.svelte';
import { PlaylistQueryKeyFactory } from './PlaylistQueryKeyFactory';

// staleTime 0: the playlist list must reflect creates/deletes/imports on every
// navigation (it can be mutated from elsewhere - e.g. the Add-to-playlist modal -
// without an explicit invalidate). Stale-while-revalidate still renders the cached
// list instantly; the user-scoped key keeps per-account isolation (AMU-5).
export const getPlaylistListQuery = (getEnabled: Getter<boolean>) =>
	createQuery(() => ({
		staleTime: 0,
		queryKey: PlaylistQueryKeyFactory.list(authStore.user?.id),
		queryFn: () => fetchPlaylists(),
		enabled: getEnabled()
	}));

export const getPlaylistDetailQuery = (getId: Getter<string>, getEnabled: Getter<boolean>) =>
	createQuery(() => ({
		staleTime: 0,
		refetchOnWindowFocus: false,
		queryKey: PlaylistQueryKeyFactory.detail(authStore.user?.id, getId()),
		queryFn: () => fetchPlaylist(getId()),
		enabled: getEnabled(),
		retry: false
	}));
