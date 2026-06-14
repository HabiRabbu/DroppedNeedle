import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import type { SourcePlaylistSummary } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import {
	SourcePlaylistsQueryKeyFactory,
	type PlaylistSource
} from './SourcePlaylistsQueryKeyFactory';

const PLAYLIST_ENDPOINTS: Record<PlaylistSource, (limit: number) => string> = {
	jellyfin: API.jellyfinLibrary.playlists,
	plex: API.plexLibrary.playlists,
	navidrome: API.navidromeLibrary.playlists
};

// Fetched separately from the library hub so a slow playlists call can't stall or
// blank the rest of the hub (the hub gathers its calls behind one short timeout).
// refetchOnMount revalidates in the background so a transient empty result self-heals.
export const getSourcePlaylistsQuery = (source: PlaylistSource, limit = 200) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.PLAYLIST_SOURCES,
		queryKey: SourcePlaylistsQueryKeyFactory.list(source, limit),
		queryFn: ({ signal }) =>
			api.get<SourcePlaylistSummary[]>(PLAYLIST_ENDPOINTS[source](limit), { signal }),
		retry: 2,
		refetchOnMount: 'always'
	}));
