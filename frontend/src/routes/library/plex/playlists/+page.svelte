<script lang="ts">
	import { resolve } from '$app/paths';
	import { API } from '$lib/constants';
	import { api } from '$lib/api/client';
	import BackButton from '$lib/components/BackButton.svelte';
	import SourcePlaylistCard from '$lib/components/SourcePlaylistCard.svelte';
	import PlexIcon from '$lib/components/PlexIcon.svelte';
	import type { SourcePlaylistSummary } from '$lib/types';

	let playlists = $state<SourcePlaylistSummary[]>([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		loadPlaylists();
	});

	async function loadPlaylists() {
		loading = true;
		error = '';
		try {
			playlists = await api.get<SourcePlaylistSummary[]>(API.plexLibrary.playlists(200));
		} catch {
			error = "Couldn't load playlists.";
		} finally {
			loading = false;
		}
	}
</script>

<div class="max-w-6xl mx-auto px-4 py-6 space-y-6">
	<div class="flex items-center gap-3">
		<BackButton fallback="/library/plex" />
		<PlexIcon class="w-6 h-6" />
		<h1 class="text-2xl font-bold">Plex Playlists</h1>
	</div>

	{#if loading}
		<div class="flex justify-center py-12">
			<span class="loading loading-spinner loading-lg"></span>
		</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else if playlists.length === 0}
		<p class="text-base-content/50 text-center py-12">No playlists were found in Plex.</p>
	{:else}
		<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
			{#each playlists as playlist (playlist.id)}
				<SourcePlaylistCard {playlist} href={resolve(`/library/plex/playlists/${playlist.id}`)} />
			{/each}
		</div>
	{/if}
</div>
