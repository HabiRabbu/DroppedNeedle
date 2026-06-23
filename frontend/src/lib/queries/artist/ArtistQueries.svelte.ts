import { API, CACHE_TTL } from '$lib/constants';
import { createInfiniteQuery, createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { ArtistQueryKeyFactory } from './ArtistQueryKeyFactory';
import { api } from '$lib/api/client';
import type {
	ArtistInfoBasic,
	ArtistInfoExtended,
	ArtistReleases,
	LastFmArtistEnrichment,
	ReleaseGroup,
	SimilarArtistsResponse,
	TopAlbumsResponse,
	TopSongsResponse
} from '$lib/types';
import type { MusicSource } from '$lib/stores/musicSource';
import { setQueryDataWithPersister } from '../QueryClient';

export const getBasicArtistQueryOptions = (artistId: string) =>
	queryOptions({
		staleTime: CACHE_TTL.ARTIST_DETAIL_BASIC,
		queryKey: ArtistQueryKeyFactory.basic(artistId),
		queryFn: ({ signal }) =>
			api.global.get<ArtistInfoBasic>(API.artist.basic(artistId), {
				signal
			})
	});

export const getBasicArtistQuery = (getArtistId: Getter<string>) =>
	createQuery(() => getBasicArtistQueryOptions(getArtistId()));

export const getExtendedArtistQuery = (getArtistId: Getter<string>) =>
	createQuery(() => ({
		staleTime: CACHE_TTL.ARTIST_DETAIL_EXTENDED,
		queryKey: ArtistQueryKeyFactory.extended(getArtistId()),
		queryFn: ({ signal }) =>
			api.global.get<ArtistInfoExtended>(API.artist.extended(getArtistId()), {
				signal
			})
	}));

export const getSimilarArtistsQuery = (
	getParams: Getter<{ artistId: string; source: MusicSource }>
) =>
	createQuery(() => {
		const { artistId, source } = getParams();
		return {
			staleTime: CACHE_TTL.ARTIST_DISCOVERY,
			queryKey: ArtistQueryKeyFactory.similarArtists(artistId, source),
			queryFn: ({ signal }) =>
				api.global.get<SimilarArtistsResponse>(API.artist.similarArtists(artistId, source), {
					signal
				})
		};
	});

export const getArtistTopAlbumsQuery = (
	getParams: Getter<{ artistId: string; source: MusicSource }>
) =>
	createQuery(() => {
		const { artistId, source } = getParams();
		return {
			staleTime: CACHE_TTL.ARTIST_DISCOVERY,
			queryKey: ArtistQueryKeyFactory.topAlbums(artistId, source),
			queryFn: ({ signal }) =>
				api.global.get<TopAlbumsResponse>(API.artist.topAlbums(artistId, source), {
					signal
				})
		};
	});

export const getArtistTopSongsQuery = (
	getParams: Getter<{ artistId: string; source: MusicSource }>
) =>
	createQuery(() => {
		const { artistId, source } = getParams();
		return {
			staleTime: CACHE_TTL.ARTIST_DISCOVERY,
			queryKey: ArtistQueryKeyFactory.topSongs(artistId, source),
			queryFn: ({ signal }) =>
				api.global.get<TopSongsResponse>(API.artist.topSongs(artistId, source), {
					signal
				})
		};
	});

export const getArtistLastFmEnrichmentQuery = (
	getParams: Getter<{ artistId: string; artistName?: string }>
) =>
	createQuery(() => {
		const { artistId, artistName } = getParams();
		return {
			staleTime: CACHE_TTL.ARTIST_DETAIL_LASTFM,
			queryKey: ArtistQueryKeyFactory.lastFmEnrichment(artistId, artistName),
			queryFn: ({ signal }) =>
				api.global.get<LastFmArtistEnrichment>(API.artist.lastFmEnrichment(artistId, artistName!), {
					signal
				}),
			enabled: () => !!artistName
		};
	});

const BATCH_SIZE = 50;

export const getArtistReleasesInfiniteQuery = (getArtistId: Getter<string>) =>
	createInfiniteQuery(() => ({
		staleTime: CACHE_TTL.ARTIST_DETAIL_BASIC,
		queryKey: ArtistQueryKeyFactory.releases(getArtistId()),
		initialPageParam: 0,
		queryFn: async ({ pageParam = 0, signal }) => {
			const response = await api.global.get<ArtistReleases>(
				API.artist.releases(getArtistId(), pageParam, BATCH_SIZE),
				{ signal }
			);
			return response;
		},
		getNextPageParam: (lastPage) => {
			if (!lastPage.has_more) {
				return undefined;
			}
			if (lastPage.next_offset != null) {
				return lastPage.next_offset;
			}
			return undefined;
		}
	}));

type ArtistReleasesInfiniteQuery = ReturnType<typeof getArtistReleasesInfiniteQuery>;

export const updateArtistReleaseInCache = (
	artistId: string,
	updatedData: Partial<ReleaseGroup> & Pick<ReleaseGroup, 'id'>
) => {
	const queryKey = ArtistQueryKeyFactory.releases(artistId);
	return setQueryDataWithPersister(queryKey, (prevData: ArtistReleasesInfiniteQuery['data']) => {
		if (!prevData) return prevData;
		const updatedPages = prevData.pages.map((page) => {
			const updateRelease = (originalRelease: ReleaseGroup) => {
				if (originalRelease.id === updatedData.id) {
					return { ...originalRelease, ...updatedData };
				}
				return originalRelease;
			};

			return {
				...page,
				albums: page.albums.map(updateRelease),
				singles: page.singles.map(updateRelease),
				eps: page.eps.map(updateRelease)
			};
		});
		return { ...prevData, pages: updatedPages };
	});
};
