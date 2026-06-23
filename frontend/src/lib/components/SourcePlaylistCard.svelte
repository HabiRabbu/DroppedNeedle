<script lang="ts">
	import type { SourcePlaylistSummary } from '$lib/types';
	import { formatTotalDurationSec } from '$lib/utils/formatting';
	import { Disc3 } from 'lucide-svelte';

	interface Props {
		playlist: SourcePlaylistSummary;
		href: string;
	}

	let { playlist, href }: Props = $props();

	let imgFailed = $state(false);

	let durationText = $derived(
		playlist.duration_seconds ? formatTotalDurationSec(playlist.duration_seconds) : ''
	);

	let subtitle = $derived(
		`${playlist.track_count} track${playlist.track_count === 1 ? '' : 's'}${durationText ? ` - ${durationText}` : ''}`
	);
</script>

<div
	class="card card-sm bg-base-100 w-full shadow-sm shrink-0 group relative transition-all hover:glow-primary"
>
	<a
		{href}
		class="block relative z-0 transition-transform active:scale-95 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base-100 rounded-t-box"
		aria-label="Open {playlist.name}"
	>
		<figure class="aspect-square overflow-hidden relative">
			<div
				class="w-full h-full transition-transform duration-200 group-hover:scale-105 transform-gpu"
			>
				{#if playlist.cover_url && !imgFailed}
					<img
						src={playlist.cover_url}
						alt={playlist.name}
						class="w-full h-full object-cover"
						loading="lazy"
						onerror={() => {
							imgFailed = true;
						}}
					/>
				{:else}
					<div class="w-full h-full bg-base-200 flex items-center justify-center">
						<Disc3 class="w-14 h-14 text-base-content/20" />
					</div>
				{/if}
			</div>
		</figure>
		<div class="px-3 pt-3 pb-3">
			<h3 class="text-sm font-semibold line-clamp-1">{playlist.name}</h3>
			<p class="text-xs text-base-content/60 mt-0.5">{subtitle}</p>
			{#if playlist.is_smart}
				<span class="badge badge-xs badge-info mt-1">Smart playlist</span>
			{/if}
			{#if playlist.is_imported}
				<span class="badge badge-xs badge-success mt-1">Imported</span>
			{/if}
		</div>
	</a>
</div>
