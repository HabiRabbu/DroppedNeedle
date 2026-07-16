<script lang="ts">
	import { goto } from '$app/navigation';
	import { ChevronLeft, Disc3 } from 'lucide-svelte';
	import ArtistImage from '$lib/components/ArtistImage.svelte';
	import LibraryAlbumCard from '$lib/components/library/LibraryAlbumCard.svelte';
	import ArtistMergeDialog from '$lib/components/library/ArtistMergeDialog.svelte';
	import { authStore } from '$lib/stores/authStore.svelte';
	import {
		getLibraryArtistAlbumsQuery,
		getLibraryArtistDetailQuery
	} from '$lib/queries/library/LibraryQueries.svelte';

	interface Props {
		artistId: string;
	}

	let { artistId }: Props = $props();
	const artistQuery = getLibraryArtistDetailQuery(() => artistId);
	const albumsQuery = getLibraryArtistAlbumsQuery(() => artistId);
	const artist = $derived(artistQuery.data);
</script>

<svelte:head><title>{artist?.name ?? 'Artist'} · Library</title></svelte:head>

<main class="container mx-auto p-4 md:p-6 lg:p-8">
	<button class="btn btn-ghost btn-sm mb-5 gap-2" onclick={() => goto('/library/artists')}
		><ChevronLeft class="h-4 w-4" /> Artists</button
	>
	{#if artistQuery.isLoading}
		<div class="flex items-center gap-5">
			<div class="skeleton h-32 w-32 rounded-full"></div>
			<div class="skeleton h-12 w-64"></div>
		</div>
	{:else if artistQuery.isError || !artist}
		<div class="alert alert-error">
			<span>Couldn't load this artist.</span><button
				class="btn btn-sm"
				onclick={() => artistQuery.refetch()}>Retry</button
			>
		</div>
	{:else}
		<header class="flex flex-col gap-5 sm:flex-row sm:items-end">
			<ArtistImage
				mbid={artist.id}
				source="local"
				available={artist.musicbrainz_artist_id !== null}
				alt={artist.name}
				size="xl"
				className="shadow-xl"
			/>
			<div class="min-w-0 flex-1">
				<span class="badge badge-outline">In your library</span>
				<h1 class="mt-2 text-4xl font-black tracking-tight sm:text-5xl">{artist.name}</h1>
				<p class="mt-2 text-sm text-base-content/55">
					{artist.album_count}
					{artist.album_count === 1 ? 'album' : 'albums'} · {artist.track_count}
					{artist.track_count === 1 ? 'track' : 'tracks'}{#if artist.musicbrainz_artist_id}
						· MusicBrainz identity attached{/if}
				</p>
			</div>
			{#if authStore.isAdmin}<ArtistMergeDialog {artist} />{/if}
		</header>

		<section class="mt-8" aria-labelledby="artist-albums-title">
			<div class="flex items-center gap-2">
				<Disc3 class="h-5 w-5 text-primary" />
				<h2 id="artist-albums-title" class="text-xl font-bold">Albums</h2>
			</div>
			{#if albumsQuery.isLoading}<div
					class="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5"
				>
					{#each Array(5) as _, index (index)}<div class="skeleton aspect-square"></div>{/each}
				</div>{:else if albumsQuery.isError}<div class="alert alert-error mt-4">
					Couldn't load this artist's albums.
				</div>{:else if !albumsQuery.data?.items.length}<p class="mt-4 text-base-content/55">
					No albums in your library are credited to this artist.
				</p>{:else}<div
					class="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5"
				>
					{#each albumsQuery.data.items as album (album.id)}<LibraryAlbumCard {album} />{/each}
				</div>{/if}
		</section>
	{/if}
</main>
