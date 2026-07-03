import type { MusicSource } from '$lib/stores/musicSource';

// Every personalized discover key carries a userId dimension so a shared browser
// never serves one user's discover/radio/suggestions cache to another.
export const DiscoverQueryKeyFactory = {
	prefix: ['discover'] as const,
	discover: (userId: string | null | undefined, source: MusicSource) =>
		[...DiscoverQueryKeyFactory.prefix, userId ?? null, source] as const,
	radio: (
		userId: string | null | undefined,
		seedType: string,
		seedId: string,
		source: MusicSource
	) =>
		[
			...DiscoverQueryKeyFactory.prefix,
			userId ?? null,
			'radio',
			seedType,
			seedId,
			{ source }
		] as const,
	playlistSuggestions: (
		userId: string | null | undefined,
		playlistId: string,
		source?: MusicSource | null
	) =>
		[
			...DiscoverQueryKeyFactory.prefix,
			userId ?? null,
			'playlist-suggestions',
			playlistId,
			source ?? null
		] as const
};
