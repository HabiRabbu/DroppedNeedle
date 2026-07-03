// Every personalized discover key carries a userId dimension so a shared browser
// never serves one user's discover/radio/suggestions cache to another.
export const DiscoverQueryKeyFactory = {
	prefix: ['discover'] as const,
	discover: (userId: string | null | undefined) =>
		[...DiscoverQueryKeyFactory.prefix, userId ?? null] as const,
	radio: (userId: string | null | undefined, seedType: string, seedId: string) =>
		[...DiscoverQueryKeyFactory.prefix, userId ?? null, 'radio', seedType, seedId] as const,
	playlistSuggestions: (userId: string | null | undefined, playlistId: string) =>
		[...DiscoverQueryKeyFactory.prefix, userId ?? null, 'playlist-suggestions', playlistId] as const
};
