<script lang="ts">
	import NowPlayingWidget from '$lib/components/NowPlayingWidget.svelte';
	import { nowPlayingMerged } from '$lib/stores/nowPlayingMerged.svelte';

	const sessions = $derived(nowPlayingMerged.sessions);
</script>

<NowPlayingWidget {sessions} />
