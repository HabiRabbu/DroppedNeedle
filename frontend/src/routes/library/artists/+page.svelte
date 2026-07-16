<script lang="ts">
	import { goto } from '$app/navigation';
	import ArtistCardSkeleton from '$lib/components/ArtistCardSkeleton.svelte';
	import ArtistImage from '$lib/components/ArtistImage.svelte';
	import { getLibraryArtistsInfiniteQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import type { ArtistSort, LibraryArtistSummary } from '$lib/types';
	import { artistHref } from '$lib/utils/entityRoutes';
	import { ChevronLeft, Mic, Search, X } from 'lucide-svelte';

	const SEARCH_DEBOUNCE_MS = 300;

	let searchInput = $state('');
	let debouncedQuery = $state('');
	let sortBy = $state<ArtistSort>('name');
	let sortOrder = $state<'asc' | 'desc'>('asc');
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	const params = $derived({ sortBy, sortOrder, q: debouncedQuery });
	const artistsQuery = getLibraryArtistsInfiniteQuery(() => params);

	// Dedupe by the same key the keyed #each uses: if the backend ever returns a
	// group on two pages, two identical keys would throw Svelte's each_key_duplicate
	// and freeze the tab. Stable ORDER BY prevents this; this is defence in depth.
	const artists = $derived.by(() => {
		const seen: Record<string, true> = Object.create(null);
		const out: LibraryArtistSummary[] = [];
		for (const page of artistsQuery.data?.pages ?? []) {
			for (const item of page.items) {
				const key = item.id;
				if (seen[key]) continue;
				seen[key] = true;
				out.push(item);
			}
		}
		return out;
	});
	const total = $derived(artistsQuery.data?.pages[0]?.total ?? 0);

	function handleSearchInput(): void {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			debouncedQuery = searchInput.trim();
		}, SEARCH_DEBOUNCE_MS);
	}

	function clearSearch(): void {
		searchInput = '';
		if (searchTimeout) clearTimeout(searchTimeout);
		debouncedQuery = '';
	}

	function handleSortChange(event: Event): void {
		const value = (event.target as HTMLSelectElement).value;
		const [newSortBy, newSortOrder] = value.split(':') as [ArtistSort, 'asc' | 'desc'];
		sortBy = newSortBy;
		sortOrder = newSortOrder;
	}
</script>

<div class="container mx-auto p-4 md:p-6 lg:p-8">
	<div class="flex items-center gap-4 mb-6">
		<button
			class="btn btn-ghost btn-circle"
			onclick={() => goto('/library')}
			aria-label="Back to library"
		>
			<ChevronLeft class="w-6 h-6" />
		</button>
		<div>
			<h1 class="text-3xl font-bold">All Artists</h1>
			<p class="text-base-content/70 text-sm mt-1">
				{total}
				{total === 1 ? 'artist' : 'artists'}
			</p>
		</div>
	</div>

	<div class="flex flex-col sm:flex-row gap-3 mb-6">
		<div class="relative group flex-1">
			<Search
				class="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-base-content/40
				group-focus-within:text-primary transition-colors duration-200 pointer-events-none"
			/>
			<input
				type="text"
				placeholder="Search artists..."
				class="input input-bordered w-full rounded-full pl-11 pr-12"
				bind:value={searchInput}
				oninput={handleSearchInput}
				aria-label="Search artists"
			/>
			{#if searchInput}
				<button
					class="absolute right-3 top-1/2 -translate-y-1/2 btn btn-sm btn-ghost btn-circle"
					onclick={clearSearch}
					aria-label="Clear search"
				>
					<X class="h-4 w-4" />
				</button>
			{/if}
		</div>
		<select
			class="select select-bordered rounded-full"
			value="{sortBy}:{sortOrder}"
			onchange={handleSortChange}
			aria-label="Sort artists"
		>
			<option value="name:asc">Name A-Z</option>
			<option value="name:desc">Name Z-A</option>
			<option value="album_count:desc">Most Albums</option>
			<option value="album_count:asc">Fewest Albums</option>
			<option value="date_added:desc">Newest First</option>
			<option value="date_added:asc">Oldest First</option>
		</select>
	</div>

	{#if artistsQuery.isError}
		<div class="alert alert-error mb-6">
			<span>Couldn't load artists</span>
			<button class="btn btn-sm btn-ghost" onclick={() => artistsQuery.refetch()}>Retry</button>
		</div>
	{:else if artistsQuery.isLoading}
		<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
			{#each Array(12) as _, i (`skeleton-${i}`)}
				<ArtistCardSkeleton />
			{/each}
		</div>
	{:else if artists.length === 0}
		<div class="flex flex-col items-center justify-center min-h-100 text-center">
			<Mic class="h-12 w-12 text-base-content/40 mb-4" strokeWidth={1.5} />
			<h2 class="text-2xl font-semibold mb-2">No artists found</h2>
			<p class="text-base-content/70 mb-4">
				{debouncedQuery
					? 'Try a different search term.'
					: "Your library doesn't contain any artists yet."}
			</p>
		</div>
	{:else}
		<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
			{#each artists as artist (artist.id)}
				<a
					href={artistHref(artist.musicbrainz_artist_id ?? artist.id)}
					class="card group bg-base-100 shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
					aria-label={`Open ${artist.name}`}
				>
					<figure class="aspect-square overflow-hidden p-3">
						<ArtistImage
							mbid={artist.id}
							source="local"
							alt={artist.name}
							size="full"
							className="h-full w-full transition-transform duration-300 group-hover:scale-105"
						/>
					</figure>
					<div class="card-body gap-1 p-3 pt-0 text-center">
						<h2 class="truncate font-semibold">{artist.name}</h2>
						<p class="text-xs text-base-content/55">
							{artist.album_count}
							{artist.album_count === 1 ? 'album' : 'albums'} · {artist.track_count}
							{artist.track_count === 1 ? 'track' : 'tracks'}
						</p>
					</div>
				</a>
			{/each}
		</div>
		{#if artistsQuery.hasNextPage}
			<div class="flex justify-center mt-6">
				<button
					class="btn btn-primary btn-outline"
					onclick={() => artistsQuery.fetchNextPage()}
					disabled={artistsQuery.isFetchingNextPage}
				>
					{#if artistsQuery.isFetchingNextPage}
						<span class="loading loading-spinner loading-sm"></span>
					{/if}
					Load More ({artists.length} / {total})
				</button>
			</div>
		{/if}
	{/if}
</div>
