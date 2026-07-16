<script lang="ts">
	import { API } from '$lib/constants';
	import { api } from '$lib/api/client';
	import { getCoverUrl } from '$lib/utils/errorHandling';
	import { buildQueueItemsFromNavidrome } from '$lib/player/queueHelpers';
	import { launchNavidromePlayback } from '$lib/player/launchNavidromePlayback';
	import {
		getNavidromeSidebarCachedData,
		getNavidromeAlbumsListCachedData,
		isNavidromeSidebarCacheStale,
		isNavidromeAlbumsListCacheStale,
		setNavidromeAlbumsListCachedData,
		setNavidromeSidebarCachedData
	} from '$lib/utils/navidromeLibraryCache';
	import {
		createLibraryController,
		type LibraryAdapter,
		type SidebarData
	} from '$lib/utils/libraryController.svelte';
	import LibraryPage from '$lib/components/LibraryPage.svelte';
	import NavidromeIcon from '$lib/components/NavidromeIcon.svelte';
	import type {
		NavidromeAlbumSummary,
		NavidromeAlbumDetail,
		NavidromePaginatedResponse,
		NavidromeSearchResponse,
		NavidromeLibraryStats,
		NavidromeTrackInfo
	} from '$lib/types';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { getNavidromeFolderPreferenceQuery } from '$lib/queries/navidrome-folders/NavidromeFolderQueries.svelte';

	const userId = authStore.user?.id ?? '';
	const folderPreferenceQuery = getNavidromeFolderPreferenceQuery(() => userId);
	const scopeRevision = $derived(folderPreferenceQuery.data?.scope_revision ?? 'unresolved');

	const adapter: LibraryAdapter<NavidromeAlbumSummary> = {
		sourceType: 'navidrome',

		getAlbumId: (a) => a.navidrome_id,
		getAlbumName: (a) => a.name,
		getArtistName: (a) => a.artist_name,
		getAlbumMbid: (a) => a.musicbrainz_id ?? undefined,
		getAlbumImageUrl: (a) => a.image_url ?? null,
		getAlbumYear: (a) => a.year,

		async fetchAlbums({ limit, offset, sortBy, sortOrder, genre, search, signal }) {
			if (search) {
				const data: NavidromeSearchResponse = await api.get(API.navidromeLibrary.search(search), {
					signal
				});
				const items = data.albums ?? [];
				return { items, total: items.length };
			}
			const params = [
				['limit', String(limit)],
				['offset', String(offset)],
				['sort_by', sortBy],
				['sort_order', sortOrder],
				...(genre ? ([['genre', genre]] as const) : [])
			];
			const query = params
				.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
				.join('&');
			const data: NavidromePaginatedResponse = await api.get(
				`${API.navidromeLibrary.albums()}?${query}`,
				{ signal }
			);
			return { items: data.items, total: data.total };
		},

		async fetchSidebarData(signal, current) {
			const [recentRes, favRes, genreRes, statsRes] = await Promise.allSettled([
				api.get<NavidromeAlbumSummary[]>(API.navidromeLibrary.recent(), { signal }),
				api.get<NavidromeAlbumSummary[]>(API.navidromeLibrary.favorites(), { signal }),
				api.get<string[]>(API.navidromeLibrary.genres(), { signal }),
				api.get<NavidromeLibraryStats>(API.navidromeLibrary.stats(), { signal })
			]);
			const hasFreshData =
				recentRes.status === 'fulfilled' ||
				favRes.status === 'fulfilled' ||
				genreRes.status === 'fulfilled' ||
				statsRes.status === 'fulfilled';
			return {
				data: {
					recentAlbums: recentRes.status === 'fulfilled' ? recentRes.value : current.recentAlbums,
					favoriteAlbums: favRes.status === 'fulfilled' ? favRes.value : current.favoriteAlbums,
					genres: genreRes.status === 'fulfilled' ? genreRes.value : current.genres,
					moods: [],
					stats:
						statsRes.status === 'fulfilled'
							? (statsRes.value as unknown as Record<string, unknown>)
							: current.stats
				},
				hasFreshData
			};
		},

		async fetchAlbumQueueItems(album) {
			const detail: NavidromeAlbumDetail = await api.get(
				API.navidromeLibrary.albumDetail(album.navidrome_id)
			);
			const tracks: NavidromeTrackInfo[] = detail.tracks ?? [];
			if (tracks.length === 0) return [];
			const sorted = [...tracks].sort((a, b) => a.track_number - b.track_number);
			return buildQueueItemsFromNavidrome(sorted, {
				albumId: album.musicbrainz_id || album.navidrome_id,
				albumName: album.name,
				artistName: album.artist_name,
				coverUrl: album.image_url ?? null,
				artistId: album.artist_musicbrainz_id ?? undefined
			});
		},

		async launchPlayback(album, shuffle) {
			const detail: NavidromeAlbumDetail = await api.get(
				API.navidromeLibrary.albumDetail(album.navidrome_id)
			);
			const tracks: NavidromeTrackInfo[] = detail.tracks ?? [];
			if (tracks.length === 0) return;
			launchNavidromePlayback(tracks, 0, shuffle, {
				albumId: album.musicbrainz_id || album.navidrome_id,
				albumName: album.name,
				artistName: album.artist_name,
				coverUrl: getCoverUrl(album.image_url ?? null, album.musicbrainz_id || album.navidrome_id)
			});
		},

		getAlbumsListCached: (key) => getNavidromeAlbumsListCachedData(userId, scopeRevision, key),
		setAlbumsListCached: (key, data) =>
			setNavidromeAlbumsListCachedData(data, userId, scopeRevision, key),
		isAlbumsListCacheStale: (ts) => isNavidromeAlbumsListCacheStale(ts),
		getSidebarCached: () => {
			const c = getNavidromeSidebarCachedData(userId, scopeRevision);
			if (!c) return null;
			return {
				data: {
					...c.data,
					favoriteAlbums: c.data.favoriteAlbums ?? [],
					genres: c.data.genres ?? [],
					moods: []
				} as SidebarData<NavidromeAlbumSummary>,
				timestamp: c.timestamp
			};
		},
		setSidebarCached: (data) =>
			setNavidromeSidebarCachedData(
				{
					recentAlbums: data.recentAlbums,
					favoriteAlbums: data.favoriteAlbums,
					genres: data.genres,
					stats: data.stats as NavidromeLibraryStats | null
				},
				userId,
				scopeRevision
			),
		isSidebarCacheStale: (ts) => isNavidromeSidebarCacheStale(ts),

		sortOptions: [
			{ value: 'name', label: 'Name' },
			{ value: 'date_added', label: 'Date Added' },
			{ value: 'year', label: 'Year' }
		],
		defaultSortBy: 'name',
		ascValue: 'asc',
		descValue: 'desc',
		getDefaultSortOrder: (field) => (field === 'name' ? 'asc' : 'desc'),
		supportsGenres: true,
		supportsMoods: false,
		supportsDecades: false,
		supportsTags: false,
		supportsFavorites: true,
		supportsShuffle: true,
		errorMessage: "Couldn't connect to Navidrome."
	};

	const ctrl = createLibraryController(adapter);

	const urlSearch = new URLSearchParams(window.location.search).get('search');
	if (urlSearch) {
		ctrl.searchQuery = urlSearch;
	}
</script>

<LibraryPage
	{ctrl}
	headerTitle="Navidrome Library"
	backHref="/library/navidrome"
	contextMenuBackdrop
	emptyTitle="No albums found"
	emptyDescription="Make sure Navidrome is set up and has at least one music library."
>
	{#snippet headerIcon()}
		<span style="color: rgb(var(--brand-navidrome));">
			<NavidromeIcon class="h-8 w-8" />
		</span>
	{/snippet}

	{#snippet cardTopLeftBadge(album)}
		<div class="badge badge-sm gap-1 badge-primary">
			<NavidromeIcon class="h-3 w-3" />
		</div>
		{#if !album.musicbrainz_id}
			<div
				class="badge badge-sm badge-warning gap-1 opacity-80"
				title="Not matched in library - search only"
			>
				?
			</div>
		{/if}
	{/snippet}

	{#snippet emptyIcon()}
		<NavidromeIcon class="h-12 w-12 opacity-20" />
	{/snippet}
</LibraryPage>
