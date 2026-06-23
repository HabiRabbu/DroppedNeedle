import type { AlbumSort, ArtistSort } from '$lib/types';

export const LibraryQueryKeyFactory = {
	all: ['library'] as const,
	albums: (page: number, sort: AlbumSort, q: string, format: string) =>
		[...LibraryQueryKeyFactory.all, 'albums', { page, sort, q, format }] as const,
	artists: (sortBy: ArtistSort, sortOrder: string, q: string) =>
		[...LibraryQueryKeyFactory.all, 'artists', { sortBy, sortOrder, q }] as const,
	album: (mbid: string) => [...LibraryQueryKeyFactory.all, 'album', mbid] as const,
	stats: () => [...LibraryQueryKeyFactory.all, 'stats'] as const,
	scanSchedule: () => [...LibraryQueryKeyFactory.all, 'scan-schedule'] as const,
	scanStatus: () => [...LibraryQueryKeyFactory.all, 'scan-status'] as const,
	unmatched: () => [...LibraryQueryKeyFactory.all, 'unmatched'] as const,
	settings: () => [...LibraryQueryKeyFactory.all, 'settings'] as const,
	albumSearch: (q: string) => [...LibraryQueryKeyFactory.all, 'album-search', q] as const,
	albumTracks: (mbid: string) => [...LibraryQueryKeyFactory.all, 'album-tracks', mbid] as const,
	search: (q: string) => [...LibraryQueryKeyFactory.all, 'search', q] as const,
	artistThumbs: () => [...LibraryQueryKeyFactory.all, 'artist-thumbs'] as const
};
