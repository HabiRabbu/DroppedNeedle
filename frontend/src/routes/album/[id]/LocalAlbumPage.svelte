<script lang="ts">
	import { goto } from '$app/navigation';
	import { ChevronLeft, Disc3, ListMusic, Play, Shuffle } from 'lucide-svelte';
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import LibraryFormatBadge from '$lib/components/library/LibraryFormatBadge.svelte';
	import AlbumIdentificationPanel from '$lib/components/library/AlbumIdentificationPanel.svelte';
	import AlbumOrganizationDialog from '$lib/components/library/AlbumOrganizationDialog.svelte';
	import LocalAlbumTrackList from '$lib/components/library/LocalAlbumTrackList.svelte';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { playerStore } from '$lib/stores/player.svelte';
	import { buildDiscoveryQueueFromLocal } from '$lib/player/queueHelpers';
	import {
		getLibraryAlbumDetailQuery,
		getLibraryAlbumTracksQuery
	} from '$lib/queries/library/LibraryQueries.svelte';

	interface Props {
		albumId: string;
	}

	let { albumId }: Props = $props();
	const albumQuery = getLibraryAlbumDetailQuery(() => albumId);
	const tracksQuery = getLibraryAlbumTracksQuery(() => albumId);
	const album = $derived(albumQuery.data);
	const tracks = $derived(tracksQuery.data?.items ?? []);

	const identityLabel = $derived(
		album?.identification_status === 'identified'
			? 'Identified'
			: album?.identification_status === 'needs_review'
				? 'Needs review'
				: album?.identification_status === 'keep_tagged'
					? 'Keep as tagged'
					: album?.identification_status === 'manual_identity_needs_review'
						? 'Manual identity needs review'
						: 'Local metadata'
	);

	function play(shuffle: boolean): void {
		const queue = buildDiscoveryQueueFromLocal(tracks);
		if (!queue.length) return;
		playerStore.playQueue(queue, 0, shuffle);
	}
</script>

<svelte:head><title>{album?.title ?? 'Album'} · Library</title></svelte:head>

<main class="container mx-auto p-4 md:p-6 lg:p-8">
	<button class="btn btn-ghost btn-sm mb-5 gap-2" onclick={() => goto('/library/albums')}>
		<ChevronLeft class="h-4 w-4" /> Albums
	</button>

	{#if albumQuery.isLoading}
		<div class="grid gap-6 md:grid-cols-[16rem_1fr]">
			<div class="skeleton aspect-square w-full rounded-2xl"></div>
			<div class="space-y-3">
				<div class="skeleton h-10 w-2/3"></div>
				<div class="skeleton h-5 w-1/3"></div>
				<div class="skeleton h-32 w-full"></div>
			</div>
		</div>
	{:else if albumQuery.isError || !album}
		<div class="alert alert-error">
			<span>Couldn't load this album.</span><button
				class="btn btn-sm"
				onclick={() => albumQuery.refetch()}>Retry</button
			>
		</div>
	{:else}
		<header class="grid gap-6 md:grid-cols-[16rem_1fr] md:items-end">
			<AlbumImage
				mbid={album.id}
				source="local"
				available={album.cover_available}
				alt={`Cover for ${album.title}`}
				size="full"
				className="aspect-square w-full rounded-2xl shadow-xl"
			/>
			<div class="min-w-0">
				<div class="flex flex-wrap items-center gap-2">
					<span class="badge badge-outline">{identityLabel}</span>
					<LibraryFormatBadge format={album.format} />
					{#if album.is_compilation}<span class="badge badge-ghost">Compilation</span>{/if}
				</div>
				<h1 class="mt-3 text-3xl font-black tracking-tight sm:text-5xl">{album.title}</h1>
				<a
					href={`/artist/${album.musicbrainz_artist_id ?? album.artist_id}`}
					class="mt-2 inline-block text-lg text-base-content/65 hover:underline"
					>{album.artist_name || 'Unknown album artist'}</a
				>
				<p class="mt-2 text-sm text-base-content/50">
					{album.year ?? 'Year unknown'} · {album.track_count}
					{album.track_count === 1 ? 'track' : 'tracks'}
					{#if album.musicbrainz_release_group_id}
						· MusicBrainz identity attached{/if}
				</p>
				<div class="mt-5 flex flex-wrap items-center gap-2">
					<button
						class="btn btn-primary gap-2"
						disabled={!tracks.length}
						onclick={() => play(false)}><Play class="h-4 w-4 fill-current" /> Play</button
					>
					<button class="btn btn-ghost gap-2" disabled={!tracks.length} onclick={() => play(true)}
						><Shuffle class="h-4 w-4" /> Shuffle</button
					>
					{#if authStore.isAdmin}<AlbumIdentificationPanel {album} /><AlbumOrganizationDialog
							{album}
							{tracks}
						/>{/if}
				</div>
				{#if album.review_id && authStore.isAdmin}
					<a
						class="link link-warning mt-3 inline-block text-sm"
						href={`/library/review?review=${album.review_id}`}>Open identification review</a
					>
				{/if}
			</div>
		</header>

		<section class="mt-8" aria-labelledby="local-tracks-title">
			<div class="flex items-center gap-2">
				<ListMusic class="h-5 w-5 text-primary" />
				<h2 id="local-tracks-title" class="text-xl font-bold">Tracks</h2>
			</div>
			{#if tracksQuery.isLoading}
				<div class="mt-3 space-y-2">
					{#each Array(8) as _, index (index)}<div class="skeleton h-14 w-full"></div>{/each}
				</div>
			{:else if tracksQuery.isError}
				<div class="alert alert-error mt-3">Couldn't load tracks.</div>
			{:else if !tracks.length}
				<div class="mt-3 rounded-box bg-base-200 p-6 text-center text-base-content/55">
					<Disc3 class="mx-auto h-8 w-8 opacity-30" />
					<p class="mt-2">No playable tracks are attached to this album.</p>
				</div>
			{:else}
				<LocalAlbumTrackList {tracks} />
			{/if}
		</section>

		<section
			class="mt-6 rounded-box border border-base-content/10 bg-base-200/35 p-4"
			aria-labelledby="provider-features-title"
		>
			<h2 id="provider-features-title" class="font-semibold">Alternate editions</h2>
			{#if album.musicbrainz_release_group_id}
				<a class="btn btn-outline btn-sm mt-3" href={`/album/${album.musicbrainz_release_group_id}`}
					>Browse alternate editions</a
				>
			{:else}
				<button class="btn btn-outline btn-sm mt-3" disabled>Browse alternate editions</button>
				<p class="mt-2 text-sm text-base-content/60">
					Identify this album before searching for alternate editions.
				</p>
			{/if}
		</section>
	{/if}
</main>
