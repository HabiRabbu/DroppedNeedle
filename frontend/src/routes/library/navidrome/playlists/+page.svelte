<script lang="ts">
	import BackButton from '$lib/components/BackButton.svelte';
	import SourcePlaylistCard from '$lib/components/SourcePlaylistCard.svelte';
	import { getSourcePlaylistsQuery } from '$lib/queries/playlists/SourcePlaylistsQuery.svelte';
	import NavidromeIcon from '$lib/components/NavidromeIcon.svelte';

	const playlistsQuery = getSourcePlaylistsQuery('navidrome');
	let playlists = $derived(playlistsQuery.data ?? []);
</script>

<div class="max-w-6xl mx-auto px-4 py-6 space-y-6">
	<div class="flex items-center gap-3">
		<BackButton fallback="/library/navidrome" />
		<NavidromeIcon class="w-6 h-6" />
		<h1 class="text-2xl font-bold">Navidrome Playlists</h1>
	</div>

	{#if playlistsQuery.isPending}
		<div class="flex justify-center py-12">
			<span class="loading loading-spinner loading-lg"></span>
		</div>
	{:else if playlistsQuery.isError}
		<div class="alert alert-error">Couldn't load playlists.</div>
	{:else if playlists.length === 0}
		<p class="text-base-content/50 text-center py-12">No playlists were found in Navidrome.</p>
	{:else}
		<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
			{#each playlists as playlist (playlist.id)}
				<SourcePlaylistCard {playlist} href="/library/navidrome/playlists/{playlist.id}" />
			{/each}
		</div>
	{/if}
</div>
