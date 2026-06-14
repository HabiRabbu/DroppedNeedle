export type PlaylistSource = 'jellyfin' | 'plex' | 'navidrome';

export const SourcePlaylistsQueryKeyFactory = {
	prefix: ['source-playlists'] as const,
	list: (source: PlaylistSource, limit: number) =>
		[...SourcePlaylistsQueryKeyFactory.prefix, source, limit] as const
};
