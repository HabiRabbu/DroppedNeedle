export const GenreQueryKeyFactory = {
	prefix: ['genre'] as const,
	detail: (userId: string | null | undefined, genre: string) =>
		[...GenreQueryKeyFactory.prefix, userId ?? null, genre.trim().toLocaleLowerCase()] as const,
	artistPages: (userId: string | null | undefined, genre: string) =>
		[...GenreQueryKeyFactory.detail(userId, genre), 'artists'] as const,
	albumPages: (userId: string | null | undefined, genre: string) =>
		[...GenreQueryKeyFactory.detail(userId, genre), 'albums'] as const
};
