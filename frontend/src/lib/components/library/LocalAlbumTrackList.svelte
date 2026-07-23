<script lang="ts">
	import { Play } from 'lucide-svelte';
	import { playerStore } from '$lib/stores/player.svelte';
	import { buildDiscoveryQueueFromLocal } from '$lib/player/queueHelpers';
	import { formatDurationSec } from '$lib/utils/formatting';
	import type { NativeTrackListItem } from '$lib/types';
	import { artistHref } from '$lib/utils/entityRoutes';

	interface Props {
		tracks: NativeTrackListItem[];
	}

	let { tracks }: Props = $props();
</script>

<ol
	class="mt-3 divide-y divide-base-content/10 overflow-hidden rounded-box border border-base-content/10 bg-base-100"
>
	{#each tracks as track, index (track.id)}
		<li class="group flex items-center gap-3 px-3 py-2.5">
			<button
				class="btn btn-ghost btn-circle btn-sm"
				onclick={() => playerStore.playQueue(buildDiscoveryQueueFromLocal(tracks), index, false)}
				aria-label={`Play ${track.title}`}><Play class="h-4 w-4" /></button
			>
			<span class="w-9 shrink-0 text-right text-xs tabular-nums text-base-content/40"
				>{track.disc_number}.{track.track_number}</span
			>
			<div class="min-w-0 flex-1">
				<p class="truncate font-medium">{track.title}</p>
				<a
					href={artistHref(track.musicbrainz_artist_id ?? track.artist_id)}
					class="truncate text-xs text-base-content/55 hover:underline"
					>{track.artist_name || 'Unknown artist'}</a
				>
			</div>
			{#if track.format}<span class="hidden text-xs uppercase text-base-content/40 sm:block"
					>{track.format}</span
				>{/if}
			<span class="text-xs tabular-nums text-base-content/45"
				>{formatDurationSec(track.duration_seconds)}</span
			>
		</li>
	{/each}
</ol>
