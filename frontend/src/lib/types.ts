export type Artist = {
	title: string;
	musicbrainz_id: string;
	in_library: boolean;
	cover_url?: string | null;
	thumb_url?: string | null;
	fanart_url?: string | null;
	banner_url?: string | null;
	disambiguation?: string | null;
	type_info?: string | null;
	release_group_count?: number | null;
	listen_count?: number | null;
	score?: number;
};

export type Album = {
	title: string;
	artist: string | null;
	year: number | null;
	musicbrainz_id: string;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	cover_url?: string | null;
	album_thumb_url?: string | null;
	album_back_url?: string | null;
	album_cdart_url?: string | null;
	album_spine_url?: string | null;
	album_3d_case_url?: string | null;
	album_3d_flat_url?: string | null;
	album_3d_face_url?: string | null;
	album_3d_thumb_url?: string | null;
	type_info?: string | null;
	disambiguation?: string | null;
	track_count?: number | null;
	listen_count?: number | null;
	score?: number;
};

export type LibraryAlbum = {
	artist: string;
	album: string;
	year?: number | null;
	monitored: boolean;
	quality?: string | null;
	cover_url?: string | null;
	musicbrainz_id?: string | null;
	artist_mbid?: string | null;
	date_added?: number | null;
};

export type SearchResults = {
	artists: Artist[];
	albums: Album[];
	top_artist?: Artist | null;
	top_album?: Album | null;
};

export type SuggestResult = {
	type: 'artist' | 'album';
	title: string;
	artist?: string | null;
	year?: number | null;
	musicbrainz_id: string;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	disambiguation?: string | null;
	score: number;
};

export type EnrichmentSource = 'listenbrainz' | 'lastfm' | 'none';

export type ArtistEnrichment = {
	musicbrainz_id: string;
	release_group_count?: number | null;
	listen_count?: number | null;
};

export type AlbumEnrichment = {
	musicbrainz_id: string;
	track_count?: number | null;
	listen_count?: number | null;
};

export type ArtistEnrichmentRequest = {
	musicbrainz_id: string;
	name: string;
};

export type AlbumEnrichmentRequest = {
	musicbrainz_id: string;
	artist_name: string;
	album_name: string;
};

export type EnrichmentBatchRequest = {
	artists: ArtistEnrichmentRequest[];
	albums: AlbumEnrichmentRequest[];
};

export type EnrichmentResponse = {
	artists: ArtistEnrichment[];
	albums: AlbumEnrichment[];
	source: EnrichmentSource;
};

export type ReleaseGroup = {
	id: string;
	title: string;
	type?: string;
	year?: number;
	first_release_date?: string;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
};

export type ExternalLink = {
	type: string;
	url: string;
	label: string;
	category?: string;
};

export type ArtistInfoBasic = {
	name: string;
	musicbrainz_id: string;
	disambiguation?: string | null;
	type?: string | null;
	country?: string | null;
	life_span?: {
		begin?: string | null;
		end?: string | null;
		ended?: boolean;
	} | null;
	fanart_url?: string | null;
	banner_url?: string | null;
	thumb_url?: string | null;
	fanart_url_2?: string | null;
	fanart_url_3?: string | null;
	fanart_url_4?: string | null;
	wide_thumb_url?: string | null;
	logo_url?: string | null;
	clearart_url?: string | null;
	cutout_url?: string | null;
	tags: string[];
	aliases: string[];
	external_links: ExternalLink[];
	in_library: boolean;
	in_lidarr?: boolean;
	monitored?: boolean;
	auto_download?: boolean;
	release_group_count?: number;
};

export type ArtistInfoExtended = {
	description?: string | null;
	image?: string | null;
};

export type ArtistInfo = ArtistInfoBasic & ArtistInfoExtended;

export type ArtistReleases = {
	albums: ReleaseGroup[];
	singles: ReleaseGroup[];
	eps: ReleaseGroup[];
	offset: number;
	limit: number;
	returned_count: number;
	next_offset: number | null;
	has_more: boolean;
	source_total_count: number | null;
};

export type UserPreferences = {
	primary_types: string[];
	secondary_types: string[];
	release_statuses: string[];
};

export type ReleaseTypeOption = {
	id: string;
	title: string;
	description: string;
};

export type Track = {
	position: number;
	disc_number?: number | null;
	title: string;
	length?: number | null;
	recording_id?: string | null;
};

export type AlbumInfo = {
	title: string;
	musicbrainz_id: string;
	artist_name: string;
	artist_id: string;
	release_date?: string | null;
	year?: number | null;
	type?: string | null;
	label?: string | null;
	barcode?: string | null;
	country?: string | null;
	disambiguation?: string | null;
	tracks: Track[];
	total_tracks: number;
	total_length?: number | null;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	cover_url?: string | null;
	album_thumb_url?: string | null;
	album_back_url?: string | null;
	album_cdart_url?: string | null;
	album_spine_url?: string | null;
	album_3d_case_url?: string | null;
	album_3d_flat_url?: string | null;
	album_3d_face_url?: string | null;
	album_3d_thumb_url?: string | null;
};

export type AlbumBasicInfo = {
	title: string;
	musicbrainz_id: string;
	artist_name: string;
	artist_id: string;
	release_date?: string | null;
	year?: number | null;
	type?: string | null;
	disambiguation?: string | null;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	cover_url?: string | null;
	album_thumb_url?: string | null;
};

export type AlbumTracksInfo = {
	tracks: Track[];
	total_tracks: number;
	total_length?: number | null;
	label?: string | null;
	barcode?: string | null;
	country?: string | null;
};

export type LidarrConnectionSettings = {
	lidarr_url: string;
	lidarr_api_key: string;
	quality_profile_id: number;
	metadata_profile_id: number;
	root_folder_path: string;
};

export type JellyfinConnectionSettings = {
	jellyfin_url: string;
	api_key: string;
	user_id: string;
	enabled: boolean;
};

export type ListenBrainzConnectionSettings = {
	username: string;
	user_token: string;
	enabled: boolean;
};

export type HomeSettings = {
	cache_ttl_trending: number;
	cache_ttl_personal: number;
	show_whats_hot: boolean;
	show_globally_trending: boolean;
};

export type HomeArtist = {
	mbid: string | null;
	name: string;
	image_url: string | null;
	listen_count: number | null;
	in_library: boolean;
	monitored?: boolean;
};

export type HomeAlbum = {
	mbid: string | null;
	name: string;
	artist_name: string | null;
	artist_mbid: string | null;
	image_url: string | null;
	release_date: string | null;
	listen_count: number | null;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
};

export type HomeTrack = {
	mbid: string | null;
	name: string;
	artist_name: string | null;
	artist_mbid: string | null;
	album_name: string | null;
	listen_count: number | null;
	listened_at: string | null;
	image_url?: string | null;
};

export type HomeGenre = {
	name: string;
	listen_count: number | null;
	artist_count: number | null;
	artist_mbid: string | null;
};

export type HomeSection = {
	title: string;
	type: 'artists' | 'albums' | 'tracks' | 'genres';
	items: (HomeArtist | HomeAlbum | HomeTrack | HomeGenre)[];
	source: string | null;
	fallback_message: string | null;
	connect_service: string | null;
	radio_seed_type?: string | null;
	radio_seed_id?: string | null;
};

export type ServicePrompt = {
	service: string;
	title: string;
	description: string;
	icon: string;
	color: string;
	features: string[];
};

export type HomeResponse = {
	recently_added: HomeSection | null;
	library_artists: HomeSection | null;
	library_albums: HomeSection | null;
	recommended_artists: HomeSection | null;
	trending_artists: HomeSection | null;
	popular_albums: HomeSection | null;
	recently_played: HomeSection | null;
	top_genres: HomeSection | null;
	genre_list: HomeSection | null;
	fresh_releases: HomeSection | null;
	favorite_artists: HomeSection | null;
	your_top_albums: HomeSection | null;
	weekly_exploration: WeeklyExplorationSection | null;
	service_prompts: ServicePrompt[];
	integration_status: Record<string, boolean>;
	genre_artists: Record<string, string | null>;
	genre_artist_images: Record<string, string | null>;
	discover_preview: DiscoverPreview | null;
};

export type DiscoverPreview = {
	seed_artist: string;
	seed_artist_mbid: string;
	items: HomeArtist[];
};

export type BecauseYouListenTo = {
	seed_artist: string;
	seed_artist_mbid: string;
	listen_count: number;
	section: HomeSection;
	banner_url?: string | null;
	wide_thumb_url?: string | null;
	fanart_url?: string | null;
};

export type WeeklyExplorationTrack = {
	title: string;
	artist_name: string;
	album_name: string;
	recording_mbid: string | null;
	artist_mbid: string | null;
	release_group_mbid: string | null;
	cover_url: string | null;
	duration_ms: number | null;
};

export type WeeklyExplorationSection = {
	title: string;
	playlist_date: string;
	tracks: WeeklyExplorationTrack[];
	source_url: string;
};

export type DiscoverResponse = {
	because_you_listen_to: BecauseYouListenTo[];
	discover_queue_enabled: boolean;
	fresh_releases: HomeSection | null;
	missing_essentials: HomeSection | null;
	rediscover: HomeSection | null;
	artists_you_might_like: HomeSection | null;
	popular_in_your_genres: HomeSection | null;
	genre_list: HomeSection | null;
	globally_trending: HomeSection | null;
	weekly_exploration: WeeklyExplorationSection | null;
	lastfm_weekly_artist_chart: HomeSection | null;
	lastfm_weekly_album_chart: HomeSection | null;
	lastfm_recent_scrobbles: HomeSection | null;
	daily_mixes: HomeSection[];
	radio_sections: HomeSection[];
	discover_picks: HomeSection | null;
	unexplored_genres: HomeSection | null;
	genre_artists: Record<string, string | null>;
	genre_artist_images: Record<string, string | null>;
	integration_status: Record<string, boolean>;
	service_prompts: ServicePrompt[];
	refreshing: boolean;
	service_status: Record<string, string> | null;
};

export type RadioRequest = {
	seed_type: 'artist' | 'album' | 'genre';
	seed_id: string;
	count?: number;
	source?: string | null;
};

export type PlaylistProfile = {
	artist_mbids: string[];
	genre_distribution: Record<string, string[]>;
	track_count: number;
};

export type PlaylistSuggestionsRequest = {
	playlist_id: string;
	count?: number;
};

export type PlaylistSuggestionsResponse = {
	suggestions: HomeSection;
	playlist_id: string;
	profile: PlaylistProfile;
};

export type QualityProfile = {
	id: number;
	name: string;
};

export type MetadataProfile = {
	id: number;
	name: string;
};

export type RootFolder = {
	id: string;
	path: string;
};

export type LidarrVerifyResponse = {
	success: boolean;
	message: string;
	quality_profiles: QualityProfile[];
	metadata_profiles: MetadataProfile[];
	root_folders: RootFolder[];
};

export type LidarrMetadataProfilePreferences = {
	profile_id: number;
	profile_name: string;
	primary_types: string[];
	secondary_types: string[];
	release_statuses: string[];
};

export type TrendingTimeRange = {
	range_key: string;
	label: string;
	featured: HomeArtist | null;
	items: HomeArtist[];
	total_count: number;
};

export type TrendingArtistsResponse = {
	this_week: TrendingTimeRange;
	this_month: TrendingTimeRange;
	this_year: TrendingTimeRange;
	all_time: TrendingTimeRange;
};

export type PopularTimeRange = {
	range_key: string;
	label: string;
	featured: HomeAlbum | null;
	items: HomeAlbum[];
	total_count: number;
};

export type PopularAlbumsResponse = {
	this_week: PopularTimeRange;
	this_month: PopularTimeRange;
	this_year: PopularTimeRange;
	all_time: PopularTimeRange;
};

export type TrendingArtistsRangeResponse = {
	range_key: string;
	label: string;
	items: HomeArtist[];
	offset: number;
	limit: number;
	has_more: boolean;
};

export type PopularAlbumsRangeResponse = {
	range_key: string;
	label: string;
	items: HomeAlbum[];
	offset: number;
	limit: number;
	has_more: boolean;
};

export type GenreLibrarySection = {
	artists: HomeArtist[];
	albums: HomeAlbum[];
	artist_count: number;
	album_count: number;
};

export type GenrePopularSection = {
	artists: HomeArtist[];
	albums: HomeAlbum[];
	has_more_artists: boolean;
	has_more_albums: boolean;
};

export type GenreDetailResponse = {
	genre: string;
	library: GenreLibrarySection | null;
	popular: GenrePopularSection | null;
	artists: HomeArtist[];
	total_count: number | null;
};

export type SimilarArtist = {
	musicbrainz_id: string;
	name: string;
	listen_count: number;
	in_library: boolean;
	monitored?: boolean;
	image_url?: string | null;
};

export type SimilarArtistsResponse = {
	similar_artists: SimilarArtist[];
	source: string;
	configured: boolean;
};

export type TopSong = {
	recording_mbid?: string | null;
	release_group_mbid?: string | null;
	original_release_mbid?: string | null;
	title: string;
	artist_name: string;
	release_name?: string | null;
	listen_count: number;
	disc_number?: number | null;
	track_number?: number | null;
};

export type TopSongsResponse = {
	songs: TopSong[];
	source: string;
	configured: boolean;
};

export type ResolvedTrack = {
	release_group_mbid?: string | null;
	disc_number?: number | null;
	track_number?: number | null;
	source?: string | null;
	track_source_id?: string | null;
	stream_url?: string | null;
	format?: string | null;
	duration?: number | null;
};

export type TopAlbum = {
	release_group_mbid?: string | null;
	title: string;
	artist_name: string;
	year?: number | null;
	listen_count: number;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	cover_url?: string | null;
};

export type TopAlbumsResponse = {
	albums: TopAlbum[];
	source: string;
	configured: boolean;
};

export type DiscoveryAlbum = {
	musicbrainz_id: string;
	title: string;
	artist_name: string;
	artist_id?: string | null;
	year?: number | null;
	in_library: boolean;
	requested?: boolean;
	monitored?: boolean;
	cover_url?: string | null;
};

export type SimilarAlbumsResponse = {
	albums: DiscoveryAlbum[];
	source: string;
	configured: boolean;
};

export type DiscoverQueueItemLight = {
	release_group_mbid: string;
	album_name: string;
	artist_name: string;
	artist_mbid: string;
	cover_url: string | null;
	recommendation_reason: string;
	is_wildcard: boolean;
	in_library: boolean;
	monitored?: boolean;
};

export type DiscoverQueueEnrichment = {
	artist_mbid: string | null;
	release_date: string | null;
	country: string | null;
	tags: string[];
	youtube_url: string | null;
	youtube_search_url: string;
	youtube_search_available: boolean;
	artist_description: string | null;
	listen_count: number | null;
};

export type YouTubeSearchResponse = {
	video_id: string | null;
	embed_url: string | null;
	error: string | null;
	cached: boolean;
};

export type YouTubeQuotaStatus = {
	used: number;
	limit: number;
	remaining: number;
	date: string;
};

export type TrackCacheCheckItem = {
	artist: string;
	track: string;
	cached: boolean;
};

export type DiscoverQueueItemFull = DiscoverQueueItemLight & {
	enrichment?: DiscoverQueueEnrichment;
};

export type DiscoverQueueResponse = {
	items: DiscoverQueueItemFull[];
	queue_id: string;
};

export type QueueStatusResponse = {
	status: 'idle' | 'building' | 'ready' | 'error';
	source: string;
	queue_id?: string;
	item_count?: number;
	built_at?: number;
	stale?: boolean;
	error?: string;
};

export type QueueGenerateResponse = {
	action: 'started' | 'already_building' | 'already_ready';
	status: string;
	source: string;
	queue_id?: string;
	item_count?: number;
	built_at?: number;
	stale?: boolean;
	error?: string;
};

export type MoreByArtistResponse = {
	albums: DiscoveryAlbum[];
	artist_name: string;
};

export type YouTubeLink = {
	album_id: string;
	video_id: string | null;
	album_name: string;
	artist_name: string;
	embed_url: string | null;
	cover_url: string | null;
	created_at: string;
	is_manual: boolean;
	track_count: number;
};

export type YouTubeLinkResponse = {
	link: YouTubeLink;
	quota: YouTubeQuotaStatus;
};

export type YouTubeLinkGenerateRequest = {
	artist_name: string;
	album_name: string;
	album_id: string;
	cover_url?: string | null;
};

export type YouTubeTrackLink = {
	album_id: string;
	track_number: number;
	disc_number?: number | null;
	track_name: string;
	video_id: string;
	artist_name: string;
	embed_url: string;
	created_at: string;
	album_name?: string;
};

export type YouTubeTrackLinkResponse = {
	track_link: YouTubeTrackLink;
	quota: YouTubeQuotaStatus;
};

export type YouTubeTrackLinkBatchResponse = {
	track_links: YouTubeTrackLink[];
	failed: {
		track_number: number;
		disc_number?: number | null;
		track_name: string;
		reason: string;
	}[];
	quota: YouTubeQuotaStatus;
};

export type StatusMessage = {
	title?: string | null;
	messages: string[];
};

export type ActiveRequestItem = {
	musicbrainz_id: string;
	artist_name: string;
	album_title: string;
	artist_mbid?: string | null;
	year?: number | null;
	cover_url?: string | null;
	requested_at: string;
	status: string;
	progress?: number | null;
	eta?: string | null;
	size?: number | null;
	size_remaining?: number | null;
	download_status?: string | null;
	download_state?: string | null;
	status_messages?: StatusMessage[] | null;
	error_message?: string | null;
	lidarr_queue_id?: number | null;
	quality?: string | null;
	protocol?: string | null;
	download_client?: string | null;
	user_id?: string | null;
};

export type RequestHistoryItem = {
	musicbrainz_id: string;
	artist_name: string;
	album_title: string;
	artist_mbid?: string | null;
	year?: number | null;
	cover_url?: string | null;
	requested_at: string;
	completed_at?: string | null;
	status: string;
	in_library: boolean;
	monitored?: boolean;
	user_id?: string | null;
};

export type ActiveRequestsResponse = {
	items: ActiveRequestItem[];
	count: number;
};

export type RequestHistoryResponse = {
	items: RequestHistoryItem[];
	total: number;
	page: number;
	page_size: number;
	total_pages: number;
};

export type JellyfinTrackInfo = {
	jellyfin_id: string;
	title: string;
	track_number: number;
	disc_number?: number | null;
	duration_seconds: number;
	album_name: string;
	artist_name: string;
	album_id?: string;
	codec?: string | null;
	bitrate?: number | null;
	image_url?: string | null;
};

export type JellyfinAlbumMatch = {
	found: boolean;
	jellyfin_album_id?: string | null;
	tracks: JellyfinTrackInfo[];
};

export type JellyfinAlbumSummary = {
	jellyfin_id: string;
	name: string;
	artist_name: string;
	year?: number | null;
	track_count: number;
	image_url?: string | null;
	musicbrainz_id?: string | null;
	artist_musicbrainz_id?: string | null;
	play_count?: number;
};

export type JellyfinPaginatedResponse = {
	items: JellyfinAlbumSummary[];
	total: number;
	offset: number;
	limit: number;
};

export type JellyfinSearchResponse = {
	albums: JellyfinAlbumSummary[];
	artists: JellyfinArtistSummary[];
	tracks: JellyfinTrackInfo[];
};

export type JellyfinLibraryStats = {
	total_tracks: number;
	total_albums: number;
	total_artists: number;
};

export type JellyfinArtistSummary = {
	jellyfin_id: string;
	name: string;
	image_url?: string | null;
	album_count: number;
	musicbrainz_id?: string | null;
	play_count?: number;
};

export type JellyfinArtistPage = {
	items: JellyfinArtistSummary[];
	total: number;
	offset: number;
	limit: number;
};

export type JellyfinArtistIndexEntry = {
	name: string;
	artists: JellyfinArtistSummary[];
};

export type JellyfinArtistIndexResponse = {
	index: JellyfinArtistIndexEntry[];
};

export type JellyfinTrackPage = {
	items: JellyfinTrackInfo[];
	total: number;
	offset: number;
	limit: number;
};

export type NavidromeConnectionSettings = {
	navidrome_url: string;
	username: string;
	password: string;
	enabled: boolean;
};

export type NavidromeTrackInfo = {
	navidrome_id: string;
	title: string;
	track_number: number;
	disc_number?: number | null;
	duration_seconds: number;
	album_name: string;
	artist_name: string;
	codec?: string | null;
	bitrate?: number | null;
	image_url?: string | null;
};

export type NavidromeAlbumSummary = {
	navidrome_id: string;
	name: string;
	artist_name: string;
	year?: number | null;
	track_count: number;
	image_url?: string | null;
	musicbrainz_id?: string | null;
	artist_musicbrainz_id?: string | null;
};

export type NavidromeAlbumDetail = NavidromeAlbumSummary & {
	tracks: NavidromeTrackInfo[];
};

export type NavidromeAlbumMatch = {
	found: boolean;
	navidrome_album_id?: string | null;
	tracks: NavidromeTrackInfo[];
};

export type NavidromeArtistSummary = {
	navidrome_id: string;
	name: string;
	image_url?: string | null;
	album_count: number;
	musicbrainz_id?: string | null;
};

export type NavidromeSearchResponse = {
	albums: NavidromeAlbumSummary[];
	artists: NavidromeArtistSummary[];
	tracks: NavidromeTrackInfo[];
};

export type NavidromeArtistIndexEntry = {
	name: string;
	artists: NavidromeArtistSummary[];
};

export type NavidromeArtistIndexResponse = {
	index: NavidromeArtistIndexEntry[];
};

export type NavidromeArtistPage = {
	items: NavidromeArtistSummary[];
	total: number;
	offset: number;
	limit: number;
};

export type NavidromeTrackPage = {
	items: NavidromeTrackInfo[];
	total: number;
	offset: number;
	limit: number;
};

export type NavidromeGenreSongsResponse = {
	songs: NavidromeTrackInfo[];
	genre: string;
};

export type NavidromeMusicFolder = {
	id: string;
	name: string;
};

export type NavidromeLibraryStats = {
	total_tracks: number;
	total_albums: number;
	total_artists: number;
};

export type NavidromePaginatedResponse = {
	items: NavidromeAlbumSummary[];
	total: number;
};

export type PlexConnectionSettings = {
	plex_url: string;
	plex_token: string;
	enabled: boolean;
	music_library_ids: string[];
	scrobble_to_plex: boolean;
};

export type PlexTrackInfo = {
	plex_id: string;
	title: string;
	track_number: number;
	duration_seconds: number;
	disc_number: number;
	album_name: string;
	artist_name: string;
	codec?: string | null;
	bitrate?: number | null;
	audio_channels?: number | null;
	container?: string | null;
	part_key?: string | null;
	image_url?: string | null;
};

export type PlexAlbumSummary = {
	plex_id: string;
	name: string;
	artist_name: string;
	year?: number | null;
	track_count: number;
	image_url?: string | null;
	musicbrainz_id?: string | null;
	artist_musicbrainz_id?: string | null;
	last_viewed_at?: number;
};

export type PlexAlbumDetail = PlexAlbumSummary & {
	tracks: PlexTrackInfo[];
	genres: string[];
};

export type PlexAlbumMatch = {
	found: boolean;
	plex_album_id?: string | null;
	tracks: PlexTrackInfo[];
};

export type PlexArtistSummary = {
	plex_id: string;
	name: string;
	image_url?: string | null;
	musicbrainz_id?: string | null;
};

export type PlexSearchResponse = {
	albums: PlexAlbumSummary[];
	artists: PlexArtistSummary[];
	tracks: PlexTrackInfo[];
};

export type PlexLibraryStats = {
	total_tracks: number;
	total_albums: number;
	total_artists: number;
};

export type PlexPaginatedResponse = {
	items: PlexAlbumSummary[];
	total: number;
};

export type PlexArtistPage = {
	items: PlexArtistSummary[];
	total: number;
	offset: number;
	limit: number;
};

export type PlexArtistIndexEntry = {
	name: string;
	artists: PlexArtistSummary[];
};

export type PlexArtistIndexResponse = {
	index: PlexArtistIndexEntry[];
};

export type PlexTrackPage = {
	items: PlexTrackInfo[];
	total: number;
	offset: number;
	limit: number;
};

export type PlexLibrarySection = {
	key: string;
	title: string;
};

export type HubStat = {
	label: string;
	value: number | null;
	href?: string;
};

export type BrowseHeroCard = {
	label: string;
	value: number | null;
	href: string;
	subtitle?: string;
	colorScheme: 'primary' | 'secondary' | 'accent';
	icon: 'disc' | 'users' | 'music';
};

export type ArtistIndexArtist = {
	id: string;
	name: string;
	image_url?: string | null;
	album_count?: number;
	musicbrainz_id?: string | null;
};

export type ArtistIndexEntry = {
	name: string;
	artists: ArtistIndexArtist[];
};

export type PlexHubResponse = {
	stats: PlexLibraryStats | null;
	recently_played: PlexAlbumSummary[];
	recently_added: PlexAlbumSummary[];
	all_albums_preview: PlexAlbumSummary[];
	playlists: SourcePlaylistSummary[];
	genres: string[];
};

export type PlexDiscoveryAlbum = {
	plex_id: string;
	name: string;
	artist_name: string;
	year?: number | null;
	image_url?: string | null;
};

export type PlexDiscoveryHub = {
	title: string;
	hub_type: string;
	albums: PlexDiscoveryAlbum[];
};

export type PlexDiscoveryResponse = {
	hubs: PlexDiscoveryHub[];
};

export type NavidromeHubResponse = {
	stats: NavidromeLibraryStats | null;
	recently_played: NavidromeAlbumSummary[];
	favorites: NavidromeAlbumSummary[];
	favorite_artists: NavidromeArtistSummary[];
	favorite_tracks: NavidromeTrackInfo[];
	all_albums_preview: NavidromeAlbumSummary[];
	playlists: SourcePlaylistSummary[];
	genres: string[];
};

export type JellyfinHubResponse = {
	stats: JellyfinLibraryStats | null;
	recently_played: JellyfinAlbumSummary[];
	recently_added: JellyfinAlbumSummary[];
	favorites: JellyfinAlbumSummary[];
	most_played_artists: JellyfinArtistSummary[];
	most_played_albums: JellyfinAlbumSummary[];
	all_albums_preview: JellyfinAlbumSummary[];
	playlists: SourcePlaylistSummary[];
	genres: string[];
};

export type LocalTrackInfo = {
	track_file_id: number;
	title: string;
	track_number: number;
	disc_number?: number | null;
	duration_seconds?: number | null;
	size_bytes: number;
	format: string;
	bitrate?: number | null;
	date_added?: string | null;
};

export type LocalAlbumMatch = {
	found: boolean;
	lidarr_album_id?: number | null;
	tracks: LocalTrackInfo[];
	total_size_bytes: number;
	primary_format?: string | null;
};

export type LocalAlbumSummary = {
	lidarr_album_id: number;
	musicbrainz_id: string;
	name: string;
	artist_name: string;
	artist_mbid?: string | null;
	year?: number | null;
	track_count: number;
	total_size_bytes: number;
	primary_format?: string | null;
	cover_url?: string | null;
	date_added?: string | null;
};

export type LocalPaginatedResponse = {
	items: LocalAlbumSummary[];
	total: number;
	offset: number;
	limit: number;
};

export type FormatInfo = {
	count: number;
	size_bytes: number;
	size_human: string;
};

export type LocalStorageStats = {
	total_tracks: number;
	total_albums: number;
	total_artists: number;
	total_size_bytes: number;
	total_size_human: string;
	disk_free_bytes: number;
	disk_free_human: string;
	format_breakdown: Record<string, FormatInfo>;
};

export type LocalFilesConnectionSettings = {
	enabled: boolean;
	music_path: string;
	lidarr_root_path: string;
};

export type LastFmConnectionSettings = {
	api_key: string;
	shared_secret: string;
	session_key: string;
	username: string;
	enabled: boolean;
};

export type LastFmConnectionSettingsResponse = {
	api_key: string;
	shared_secret: string;
	session_key: string;
	username: string;
	enabled: boolean;
};

export type LastFmVerifyResponse = {
	valid: boolean;
	message: string;
};

export type LastFmAuthTokenResponse = {
	token: string;
	auth_url: string;
};

export type LastFmAuthSessionResponse = {
	username: string;
	success: boolean;
	message: string;
};

export type ScrobbleSettings = {
	scrobble_to_lastfm: boolean;
	scrobble_to_listenbrainz: boolean;
};

export type NowPlayingSubmission = {
	track_name: string;
	artist_name: string;
	album_name: string;
	duration_ms: number;
	mbid?: string;
};

export type ScrobbleSubmission = {
	track_name: string;
	artist_name: string;
	album_name: string;
	timestamp: number;
	duration_ms: number;
	mbid?: string;
};

export type ServiceResult = {
	success: boolean;
	error?: string;
};

export type ScrobbleResponse = {
	accepted: boolean;
	services: Record<string, ServiceResult>;
};

export type LastFmTag = {
	name: string;
	url?: string | null;
};

export type LastFmSimilarArtistDetail = {
	name: string;
	mbid?: string | null;
	match: number;
	url?: string | null;
};

export type LastFmArtistEnrichment = {
	bio?: string | null;
	summary?: string | null;
	tags: LastFmTag[];
	listeners: number;
	playcount: number;
	similar_artists: LastFmSimilarArtistDetail[];
	url?: string | null;
};

export type LastFmAlbumEnrichment = {
	summary?: string | null;
	tags: LastFmTag[];
	listeners: number;
	playcount: number;
	url?: string | null;
};

export type SourcePlaylistSummary = {
	id: string;
	name: string;
	track_count: number;
	duration_seconds: number;
	cover_url: string;
	is_smart?: boolean;
	is_imported?: boolean;
	owner?: string;
	is_public?: boolean;
	updated_at?: string;
	created_at?: string;
};

export type SourcePlaylistTrack = {
	id: string;
	track_name: string;
	artist_name: string;
	album_name: string;
	album_id: string;
	artist_id?: string;
	plex_rating_key?: string;
	duration_seconds: number;
	track_number: number;
	disc_number: number;
	cover_url: string;
};

export type SourcePlaylistDetail = {
	id: string;
	name: string;
	track_count: number;
	duration_seconds: number;
	cover_url: string;
	is_smart?: boolean;
	updated_at?: string;
	created_at?: string;
	tracks: SourcePlaylistTrack[];
};

export type SourceImportResult = {
	musicseerr_playlist_id: string;
	tracks_imported: number;
	tracks_failed: number;
	already_imported: boolean;
};

export type PlexSessionInfo = {
	session_id: string;
	user_name: string;
	track_title: string;
	artist_name: string;
	album_name: string;
	cover_url: string;
	player_device: string;
	player_platform: string;
	player_state: string;
	is_direct_play: boolean;
	progress_ms: number;
	duration_ms: number;
	audio_codec: string;
	audio_channels: number;
	bitrate: number;
};

export type PlexSessionsResponse = {
	sessions: PlexSessionInfo[];
	available: boolean;
};

export type NavidromeNowPlayingEntry = {
	user_name: string;
	minutes_ago: number;
	player_name: string;
	track_name: string;
	artist_name: string;
	album_name: string;
	album_id: string;
	cover_art_id: string;
	duration_seconds: number;
	estimated_position_seconds?: number;
};

export type NavidromeNowPlayingResponse = {
	entries: NavidromeNowPlayingEntry[];
};

export type JellyfinSessionInfo = {
	session_id: string;
	user_name: string;
	device_name: string;
	client_name: string;
	track_name: string;
	artist_name: string;
	album_name: string;
	album_id: string;
	cover_url: string;
	position_seconds: number;
	duration_seconds: number;
	is_paused: boolean;
	play_method: string;
	audio_codec: string;
	bitrate: number;
};

export type JellyfinSessionsResponse = {
	sessions: JellyfinSessionInfo[];
};

export type NowPlayingSession = {
	id: string;
	user_name: string;
	track_name: string;
	artist_name: string;
	album_name: string;
	cover_url: string;
	device_name: string;
	is_paused: boolean;
	source?: 'jellyfin' | 'navidrome' | 'plex';
	progress_ms?: number;
	duration_ms?: number;
	audio_codec?: string;
	bitrate?: number;
	_isLocal?: boolean;
};

export type NavidromeArtistInfo = {
	navidrome_id: string;
	name: string;
	biography: string;
	image_url: string;
	similar_artists: NavidromeArtistSummary[];
};

export type PlexHistoryEntry = {
	rating_key: string;
	track_title: string;
	artist_name: string;
	album_name: string;
	cover_url: string;
	viewed_at: string;
	device_name: string;
};

export type PlexHistoryResponse = {
	entries: PlexHistoryEntry[];
	total: number;
	limit: number;
	offset: number;
	available: boolean;
};

export type PlexAnalyticsItem = {
	name: string;
	subtitle: string;
	play_count: number;
	cover_url: string | null;
};

export type PlexAnalyticsResponse = {
	top_artists: PlexAnalyticsItem[];
	top_albums: PlexAnalyticsItem[];
	top_tracks: PlexAnalyticsItem[];
	total_listens: number;
	listens_last_7_days: number;
	listens_last_30_days: number;
	total_hours: number;
	is_complete: boolean;
	entries_analyzed: number;
};

export type NavidromeAlbumInfo = {
	album_id: string;
	notes: string;
	musicbrainz_id: string;
	lastfm_url: string;
	image_url: string;
};

export type LyricLine = {
	text: string;
	start_seconds: number | null;
};

export type NavidromeLyricsResponse = {
	text: string;
	is_synced: boolean;
	lines: LyricLine[];
};

export type JellyfinLyricsLine = {
	text: string;
	start_seconds: number | null;
};

export type JellyfinLyricsResponse = {
	lines: JellyfinLyricsLine[];
	is_synced: boolean;
	lyrics_text: string;
};

export type JellyfinFavoritesExpanded = {
	albums: JellyfinAlbumSummary[];
	artists: JellyfinArtistSummary[];
};

export type JellyfinFilterFacets = {
	years: number[];
	tags: string[];
	studios: string[];
};
