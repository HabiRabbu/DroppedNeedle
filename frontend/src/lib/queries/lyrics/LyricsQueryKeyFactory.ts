import type { SourceType } from '$lib/player/types';

export const LyricsQueryKeyFactory = {
	prefix: ['lyrics'] as const,
	lyrics: (
		userId: string | undefined,
		navidromeScope: string | undefined,
		sourceType: SourceType | undefined,
		trackSourceId: string | undefined,
		artistName: string | undefined,
		trackName: string | undefined
	) =>
		[
			...LyricsQueryKeyFactory.prefix,
			userId,
			navidromeScope,
			sourceType,
			trackSourceId,
			artistName,
			trackName
		] as const
};
