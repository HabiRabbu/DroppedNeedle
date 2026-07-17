import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { HomeQueryKeyFactory } from '$lib/queries/HomeQueryKeyFactory';
import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';
import { PlaylistQueryKeyFactory } from '$lib/queries/playlists/PlaylistQueryKeyFactory';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { authStore } from '$lib/stores/authStore.svelte';
import type { SourceImportResult, SourcePlaylistSource } from '$lib/types';

import { SourcePlaylistQueryKeyFactory } from './SourcePlaylistQueryKeyFactory';

function importUrl(source: SourcePlaylistSource, playlistId: string): string {
	switch (source) {
		case 'jellyfin':
			return API.jellyfinLibrary.playlistImport(playlistId);
		case 'navidrome':
			return API.navidromeLibrary.playlistImport(playlistId);
		case 'plex':
			return API.plexLibrary.playlistImport(playlistId);
	}
}

export const createSourcePlaylistImportMutation = (getSource: () => SourcePlaylistSource) =>
	createMutation(() => ({
		mutationFn: (playlistId: string) =>
			api.global.post<SourceImportResult>(importUrl(getSource(), playlistId)),
		onSuccess: async () => {
			const userId = authStore.user?.id;
			const source = getSource();
			await Promise.all([
				invalidateQueriesWithPersister({
					queryKey: SourcePlaylistQueryKeyFactory.source(userId, source)
				}),
				invalidateQueriesWithPersister({ queryKey: PlaylistQueryKeyFactory.list(userId) }),
				invalidateQueriesWithPersister({ queryKey: HomeQueryKeyFactory.prefix }),
				invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all })
			]);
		}
	}));
