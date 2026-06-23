<script lang="ts">
	import { getApiUrl } from '$lib/api/api-utils';
	import { page } from '$app/state';
	import { onMount, onDestroy } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import GenreArtistCard from '$lib/components/GenreArtistCard.svelte';
	import GenreAlbumCard from '$lib/components/GenreAlbumCard.svelte';
	import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
	import type { GenreDetailResponse } from '$lib/types';
	import { createAbortable } from '$lib/utils/abortController';
	import { albumHrefOrNull, artistHrefOrNull } from '$lib/utils/entityRoutes';
	import { isAbortError } from '$lib/utils/errorHandling';
	import { api } from '$lib/api/client';
	import { createLocalStorageCache } from '$lib/utils/localStorageCache';
	import { ArrowLeft, BookOpen, Music2, CircleAlert, Mic, Disc3, ChevronDown } from 'lucide-svelte';

	let genreName = $derived(page.url.searchParams.get('name') || '');
	let genreData: GenreDetailResponse | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let heroArtistMbid: string | null = $state(null);
	let heroImageLoaded = $state(false);
	const genreRequestAbortable = createAbortable();
	let lastLoadedGenre = '';

	let artistOffset = $state(0);
	let albumOffset = $state(0);
	let loadingMoreArtists = $state(false);
	let loadingMoreAlbums = $state(false);
	const PAGE_SIZE = 50;
	const genreDetailCache = createLocalStorageCache<GenreDetailResponse>(
		CACHE_KEYS.GENRE_DETAIL_CACHE,
		CACHE_TTL.GENRE_DETAIL,
		{ maxEntries: 60 }
	);

	function getGenreCacheSuffix(): string {
		return encodeURIComponent(genreName.trim().toLowerCase());
	}

	function persistGenreCache() {
		if (!genreData || !genreName) return;
		genreDetailCache.set(genreData, getGenreCacheSuffix());
	}

	async function loadHeroArtist() {
		if (!genreName) return;
		heroArtistMbid = null;
		heroImageLoaded = false;
		try {
			const data = await api.get<{ artist_mbid: string }>(
				`/api/v1/home/genre-artist/${encodeURIComponent(genreName)}`,
				{
					signal: genreRequestAbortable.signal
				}
			);
			heroArtistMbid = data.artist_mbid;
		} catch (e) {
			if (isAbortError(e)) return;
		}
	}

	async function loadGenreData() {
		if (!genreName) {
			error = 'No genre specified';
			loading = false;
			return;
		}

		const cacheSuffix = getGenreCacheSuffix();
		const cachedGenreData = genreDetailCache.get(cacheSuffix);
		const hasCachedGenreData = !!cachedGenreData?.data;
		const shouldRefresh = !cachedGenreData || genreDetailCache.isStale(cachedGenreData.timestamp);

		if (hasCachedGenreData) {
			genreData = cachedGenreData.data;
			loading = false;
		}

		if (!shouldRefresh) {
			error = '';
			return;
		}

		loading = !hasCachedGenreData;
		error = '';
		artistOffset = 0;
		albumOffset = 0;

		try {
			const data: GenreDetailResponse = await api.get(
				`/api/v1/home/genre/${encodeURIComponent(genreName)}?limit=${PAGE_SIZE}`,
				{ signal: genreRequestAbortable.signal }
			);
			genreData = data;
			genreDetailCache.set(data, cacheSuffix);
		} catch (e) {
			if (isAbortError(e)) return;
			if (!hasCachedGenreData) {
				error = "Couldn't load this genre";
			}
		} finally {
			if (!hasCachedGenreData) {
				loading = false;
			}
		}
	}

	async function loadMoreArtists() {
		if (!genreData || loadingMoreArtists || !genreData.popular?.has_more_artists) return;
		loadingMoreArtists = true;
		artistOffset += PAGE_SIZE;

		try {
			const data: GenreDetailResponse = await api.get(
				`/api/v1/home/genre/${encodeURIComponent(genreName)}?limit=${PAGE_SIZE}&artist_offset=${artistOffset}`,
				{ signal: genreRequestAbortable.signal }
			);
			if (genreData.popular && data.popular) {
				genreData.popular.artists = [...genreData.popular.artists, ...data.popular.artists];
				genreData.popular.has_more_artists = data.popular.has_more_artists;
				persistGenreCache();
			}
		} catch (e) {
			if (isAbortError(e)) return;
			artistOffset -= PAGE_SIZE;
		} finally {
			loadingMoreArtists = false;
		}
	}

	async function loadMoreAlbums() {
		if (!genreData || loadingMoreAlbums || !genreData.popular?.has_more_albums) return;
		loadingMoreAlbums = true;
		albumOffset += PAGE_SIZE;

		try {
			const data: GenreDetailResponse = await api.get(
				`/api/v1/home/genre/${encodeURIComponent(genreName)}?limit=${PAGE_SIZE}&album_offset=${albumOffset}`,
				{ signal: genreRequestAbortable.signal }
			);
			if (genreData.popular && data.popular) {
				genreData.popular.albums = [...genreData.popular.albums, ...data.popular.albums];
				genreData.popular.has_more_albums = data.popular.has_more_albums;
				persistGenreCache();
			}
		} catch (e) {
			if (isAbortError(e)) return;
			albumOffset -= PAGE_SIZE;
		} finally {
			loadingMoreAlbums = false;
		}
	}

	function loadData() {
		genreRequestAbortable.reset();
		lastLoadedGenre = genreName;
		void loadGenreData();
		void loadHeroArtist();
	}

	function cleanup() {
		genreRequestAbortable.abort();
	}

	onMount(() => {
		if (genreName) loadData();
	});
	onDestroy(cleanup);
	beforeNavigate(cleanup);

	$effect(() => {
		if (genreName && genreName !== lastLoadedGenre) loadData();
	});

	const hasLibraryContent = $derived.by(() => {
		const data = genreData;
		return (data?.library?.artists?.length ?? 0) > 0 || (data?.library?.albums?.length ?? 0) > 0;
	});
</script>

<svelte:head>
	<title>{genreName ? `${genreName}` : 'Genre'} - DroppedNeedle</title>
</svelte:head>

<div class="min-h-screen bg-base-100 relative overflow-hidden">
	{#if heroArtistMbid}
		<div
			class="absolute inset-x-0 top-0 h-96 overflow-hidden pointer-events-none"
			style="z-index: 0;"
		>
			<img
				src={getApiUrl(`/api/v1/covers/artist/${heroArtistMbid}?size=500`)}
				alt=""
				class="w-full h-full object-cover object-top transition-opacity duration-700 {heroImageLoaded
					? 'opacity-20'
					: 'opacity-0'}"
				onload={() => (heroImageLoaded = true)}
			/>
			<div
				class="absolute inset-0 bg-linear-to-b from-base-100/30 via-base-100/70 to-base-100"
			></div>
		</div>
	{/if}

	<div class="container mx-auto p-4 max-w-7xl relative" style="z-index: 1;">
		<header class="mb-10 pt-2">
			<a href="/" class="btn btn-ghost btn-sm gap-2 mb-6 -ml-2 opacity-70 hover:opacity-100">
				<ArrowLeft class="w-4 h-4" />
				Back
			</a>
			<div class="flex items-center gap-5">
				<div
					class="w-20 h-20 rounded-2xl bg-linear-to-br from-primary/30 to-secondary/30 flex items-center justify-center shrink-0"
				>
					<Music2 class="h-10 w-10 text-primary" />
				</div>
				<div>
					<h1 class="text-4xl sm:text-5xl font-bold capitalize tracking-tight">
						{genreName || 'Genre'}
					</h1>
					{#if genreData}
						<p class="text-base-content/50 mt-2 text-sm sm:text-base">
							{#if hasLibraryContent}
								{genreData.library?.artist_count ?? 0} artists · {genreData.library?.album_count ??
									0} albums in your library
							{:else}
								Explore popular {genreName} music
							{/if}
						</p>
					{/if}
				</div>
			</div>
		</header>

		{#if loading}
			<section class="mb-12" aria-label="Loading">
				<div class="flex items-center gap-3 mb-6">
					<div class="skeleton w-10 h-10 rounded-xl"></div>
					<div>
						<div class="skeleton h-6 w-48 mb-2"></div>
						<div class="skeleton h-4 w-32"></div>
					</div>
				</div>
				<div
					class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
				>
					{#each Array(12) as _, i (`genre-artist-skeleton-${i}`)}
						<div class="card bg-base-200/50">
							<div class="skeleton aspect-square rounded-t-2xl"></div>
							<div class="p-3">
								<div class="skeleton h-4 w-3/4 mb-2"></div>
								<div class="skeleton h-3 w-1/2"></div>
							</div>
						</div>
					{/each}
				</div>
			</section>

			<section class="mb-12" aria-label="Loading">
				<div class="flex items-center gap-3 mb-6">
					<div class="skeleton w-10 h-10 rounded-xl"></div>
					<div>
						<div class="skeleton h-6 w-40 mb-2"></div>
						<div class="skeleton h-4 w-28"></div>
					</div>
				</div>
				<div
					class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
				>
					{#each Array(6) as _, i (`genre-album-skeleton-${i}`)}
						<div class="card bg-base-200/50">
							<div class="skeleton aspect-square rounded-t-2xl"></div>
							<div class="p-3">
								<div class="skeleton h-4 w-3/4 mb-2"></div>
								<div class="skeleton h-3 w-1/2"></div>
							</div>
						</div>
					{/each}
				</div>
			</section>
		{:else if error}
			<div class="flex flex-col items-center justify-center py-24">
				<CircleAlert class="h-12 w-12 text-base-content/40 mb-4" strokeWidth={1.5} />
				<p class="text-base-content/70 text-lg">{error}</p>
				<button class="btn btn-primary mt-6" onclick={loadData}>Try Again</button>
			</div>
		{:else if genreData}
			{#if hasLibraryContent}
				<section class="mb-12" aria-label="From Your Library">
					<div class="flex items-center gap-3 mb-6">
						<div
							class="w-10 h-10 rounded-xl bg-success/20 flex items-center justify-center text-success"
						>
							<BookOpen class="w-5 h-5" />
						</div>
						<div>
							<h2 class="text-2xl font-bold">From Your Library</h2>
							<p class="text-sm text-base-content/50">
								{genreData.library?.artist_count ?? 0} artists · {genreData.library?.album_count ??
									0} albums
							</p>
						</div>
					</div>

					{#if (genreData.library?.artists?.length ?? 0) > 0}
						<h3 class="text-lg font-semibold mb-4 text-base-content/70">Artists</h3>
						<div
							class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 mb-8"
						>
							{#each genreData.library?.artists ?? [] as artist (artist.mbid || artist.name)}
								<GenreArtistCard
									{artist}
									showLibraryBadge={true}
									href={artistHrefOrNull(artist.mbid)}
								/>
							{/each}
						</div>
					{/if}

					{#if (genreData.library?.albums?.length ?? 0) > 0}
						<h3 class="text-lg font-semibold mb-4 text-base-content/70">Albums</h3>
						<div
							class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
						>
							{#each genreData.library?.albums ?? [] as album (album.mbid || album.name)}
								<GenreAlbumCard
									{album}
									showLibraryBadge={true}
									href={albumHrefOrNull(album.mbid)}
								/>
							{/each}
						</div>
					{/if}
				</section>
				<div class="divider my-8 opacity-30"></div>
			{/if}

			<section class="mb-12" aria-label="Popular Artists">
				<div class="flex items-center gap-3 mb-6">
					<div
						class="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center text-primary"
					>
						<Mic class="w-5 h-5" />
					</div>
					<div>
						<h2 class="text-2xl font-bold">Popular Artists</h2>
						<p class="text-sm text-base-content/50">Top {genreName} artists</p>
					</div>
				</div>

				{#if (genreData.popular?.artists?.length ?? 0) === 0}
					<div class="flex flex-col items-center justify-center py-16">
						<Mic class="h-10 w-10 text-base-content/30 mb-4" strokeWidth={1.5} />
						<p class="text-base-content/50">No artists found for this genre</p>
					</div>
				{:else}
					<div
						class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
					>
						{#each genreData.popular?.artists ?? [] as artist (artist.mbid || artist.name)}
							<GenreArtistCard {artist} href={artistHrefOrNull(artist.mbid)} />
						{/each}
					</div>
					{#if genreData.popular?.has_more_artists}
						<div class="flex justify-center mt-8">
							<button
								class="btn btn-outline btn-wide gap-2"
								onclick={loadMoreArtists}
								disabled={loadingMoreArtists}
							>
								{#if loadingMoreArtists}
									<span class="loading loading-spinner loading-sm"></span>
								{:else}
									<ChevronDown class="w-4 h-4" />
								{/if}
								View More Artists
							</button>
						</div>
					{/if}
				{/if}
			</section>

			<section class="mb-12" aria-label="Popular Albums">
				<div class="flex items-center gap-3 mb-6">
					<div
						class="w-10 h-10 rounded-xl bg-secondary/20 flex items-center justify-center text-secondary"
					>
						<Disc3 class="w-5 h-5" />
					</div>
					<div>
						<h2 class="text-2xl font-bold">Popular Albums</h2>
						<p class="text-sm text-base-content/50">Top {genreName} albums</p>
					</div>
				</div>

				{#if (genreData.popular?.albums?.length ?? 0) === 0}
					<div class="flex flex-col items-center justify-center py-16">
						<Disc3 class="h-10 w-10 text-base-content/30 mb-4" strokeWidth={1.5} />
						<p class="text-base-content/50">No albums found for this genre</p>
					</div>
				{:else}
					<div
						class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
					>
						{#each genreData.popular?.albums ?? [] as album (album.mbid || album.name)}
							<GenreAlbumCard {album} href={albumHrefOrNull(album.mbid)} />
						{/each}
					</div>
					{#if genreData.popular?.has_more_albums}
						<div class="flex justify-center mt-8">
							<button
								class="btn btn-outline btn-wide gap-2"
								onclick={loadMoreAlbums}
								disabled={loadingMoreAlbums}
							>
								{#if loadingMoreAlbums}
									<span class="loading loading-spinner loading-sm"></span>
								{:else}
									<ChevronDown class="w-4 h-4" />
								{/if}
								View More Albums
							</button>
						</div>
					{/if}
				{/if}
			</section>
		{/if}
	</div>
</div>
