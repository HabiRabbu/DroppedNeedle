<script lang="ts">
	import { page } from '$app/stores';
	import SourcePlaylistDetail from '$lib/components/SourcePlaylistDetail.svelte';
	import PlexIcon from '$lib/components/PlexIcon.svelte';

	let playlistId = $derived($page.params.id ?? '');
</script>

<SourcePlaylistDetail {playlistId} source="plex" backFallback="/library/plex/playlists">
	{#snippet icon()}
		<PlexIcon class="w-6 h-6" />
	{/snippet}
</SourcePlaylistDetail>
