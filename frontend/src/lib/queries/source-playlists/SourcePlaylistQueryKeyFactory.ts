import type { SourcePlaylistSource } from '$lib/types';

export const SourcePlaylistQueryKeyFactory = {
	prefix: ['source-playlists'] as const,
	user: (userId: string | undefined) =>
		[...SourcePlaylistQueryKeyFactory.prefix, userId ?? 'anon'] as const,
	source: (userId: string | undefined, source: SourcePlaylistSource) =>
		[...SourcePlaylistQueryKeyFactory.user(userId), source] as const,
	list: (userId: string | undefined, source: SourcePlaylistSource, limit: number) =>
		[...SourcePlaylistQueryKeyFactory.source(userId, source), 'list', limit] as const,
	detail: (userId: string | undefined, source: SourcePlaylistSource, playlistId: string) =>
		[...SourcePlaylistQueryKeyFactory.source(userId, source), 'detail', playlistId] as const
};
