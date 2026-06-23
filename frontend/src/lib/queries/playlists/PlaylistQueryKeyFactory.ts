export const PlaylistQueryKeyFactory = {
	prefix: ['playlists'] as const,
	// Keys carry the current user id so personalized playlist data never leaks across
	// a user switch on a shared browser (AMU-5).
	list: (userId: string | undefined) =>
		[...PlaylistQueryKeyFactory.prefix, userId ?? 'anon', 'list'] as const,
	detail: (userId: string | undefined, id: string) =>
		[...PlaylistQueryKeyFactory.prefix, userId ?? 'anon', 'detail', id] as const
};
