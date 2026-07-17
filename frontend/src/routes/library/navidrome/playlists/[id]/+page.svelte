<script lang="ts">
	import { page } from '$app/stores';
	import SourcePlaylistDetail from '$lib/components/SourcePlaylistDetail.svelte';
	import NavidromeIcon from '$lib/components/NavidromeIcon.svelte';

	let playlistId = $derived($page.params.id ?? '');
</script>

<SourcePlaylistDetail {playlistId} source="navidrome" backFallback="/library/navidrome/playlists">
	{#snippet icon()}
		<NavidromeIcon class="w-6 h-6" />
	{/snippet}
</SourcePlaylistDetail>
