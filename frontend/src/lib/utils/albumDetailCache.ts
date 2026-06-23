import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import type {
	AlbumBasicInfo,
	AlbumTracksInfo,
	LastFmAlbumEnrichment,
	MoreByArtistResponse,
	SimilarAlbumsResponse,
	YouTubeLink,
	YouTubeTrackLink,
	JellyfinAlbumMatch,
	LocalAlbumMatch,
	NavidromeAlbumMatch,
	PlexAlbumMatch
} from '$lib/types';
import { createLocalStorageCache } from '$lib/utils/localStorageCache';

const MAX_ALBUM_DETAIL_CACHE_ENTRIES = 120;

type AlbumDiscoveryCachePayload = {
	moreByArtist: MoreByArtistResponse | null;
	similarAlbums: SimilarAlbumsResponse | null;
};

type AlbumYouTubeCachePayload = {
	albumLink: YouTubeLink | null;
	trackLinks: YouTubeTrackLink[];
};

type AlbumSourceMatchCachePayload = {
	jellyfin: JellyfinAlbumMatch | null;
	local: LocalAlbumMatch | null;
	navidrome: NavidromeAlbumMatch | null;
	plex: PlexAlbumMatch | null;
};

export const albumBasicCache = createLocalStorageCache<AlbumBasicInfo>(
	CACHE_KEYS.ALBUM_BASIC_CACHE,
	CACHE_TTL.ALBUM_DETAIL_BASIC,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);

export const albumTracksCache = createLocalStorageCache<AlbumTracksInfo>(
	CACHE_KEYS.ALBUM_TRACKS_CACHE,
	CACHE_TTL.ALBUM_DETAIL_TRACKS,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);

export const albumDiscoveryCache = createLocalStorageCache<AlbumDiscoveryCachePayload>(
	CACHE_KEYS.ALBUM_DISCOVERY_CACHE,
	CACHE_TTL.ALBUM_DETAIL_DISCOVERY,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);

export const albumLastFmCache = createLocalStorageCache<LastFmAlbumEnrichment>(
	CACHE_KEYS.ALBUM_LASTFM_CACHE,
	CACHE_TTL.ALBUM_DETAIL_LASTFM,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);

export const albumYouTubeCache = createLocalStorageCache<AlbumYouTubeCachePayload>(
	CACHE_KEYS.ALBUM_YOUTUBE_CACHE,
	CACHE_TTL.ALBUM_DETAIL_YOUTUBE,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);

export const albumSourceMatchCache = createLocalStorageCache<AlbumSourceMatchCachePayload>(
	CACHE_KEYS.ALBUM_SOURCE_MATCH_CACHE,
	CACHE_TTL.ALBUM_DETAIL_SOURCE_MATCH,
	{ maxEntries: MAX_ALBUM_DETAIL_CACHE_ENTRIES }
);
