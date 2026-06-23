import type { MusicSource } from '$lib/stores/musicSource';

export const HomeQueryKeyFactory = {
	prefix: ['home'] as const,
	// userId dimension isolates one user's home cache from another's on a shared browser.
	home: (userId: string | null | undefined, source: MusicSource) =>
		[...HomeQueryKeyFactory.prefix, userId ?? null, source] as const
};
