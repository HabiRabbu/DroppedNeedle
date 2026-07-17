<script lang="ts">
	import SourcePlaylistList from '$lib/components/SourcePlaylistList.svelte';
	import { Tv } from 'lucide-svelte';
</script>

<SourcePlaylistList
	source="jellyfin"
	sourceLabel="Jellyfin"
	backFallback="/library/jellyfin"
	playlistBaseHref="/library/jellyfin/playlists"
>
	{#snippet icon()}
		<Tv class="h-6 w-6 text-primary" />
	{/snippet}
</SourcePlaylistList>
