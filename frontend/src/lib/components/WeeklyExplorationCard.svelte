<script lang="ts">
	import type { WeeklyExplorationTrack, YouTubeQuotaStatus } from '$lib/types';
	import { Music2, Disc3 } from 'lucide-svelte';
	import { albumHrefOrNull, artistHrefOrNull } from '$lib/utils/entityRoutes';
	import { integrationStore } from '$lib/stores/integration';
	import { libraryStore } from '$lib/stores/library';
	import AlbumRequestButton from './AlbumRequestButton.svelte';
	import TrackPreviewButton from './TrackPreviewButton.svelte';

	interface Props {
		track: WeeklyExplorationTrack;
		index: number;
		ytConfigured?: boolean;
		initialCached?: boolean | null;
		showQuota?: boolean;
		quotaInfo?: YouTubeQuotaStatus | null;
	}

	let {
		track,
		index,
		ytConfigured = false,
		initialCached = null,
		showQuota = false,
		quotaInfo = null
	}: Props = $props();

	const albumHref = $derived(albumHrefOrNull(track.release_group_mbid));
	const artistHref = $derived(artistHrefOrNull(track.artist_mbid));
	const albumMbid = $derived(track.release_group_mbid);
	const isRequested = $derived(albumMbid ? libraryStore.isRequested(albumMbid) : false);

	function formatDuration(ms: number | null): string {
		if (!ms) return '';
		const totalSec = Math.floor(ms / 1000);
		const min = Math.floor(totalSec / 60);
		const sec = totalSec % 60;
		return `${min}:${sec.toString().padStart(2, '0')}`;
	}

	let imgError = $state(false);
</script>

<div
	class="flex w-44 shrink-0 flex-col rounded-xl bg-base-100 shadow-sm
	transition-all duration-200 hover:glow-primary-soft"
>
	{#if albumHref}
		<a
			href={albumHref}
			class="group relative aspect-square w-full overflow-hidden rounded-t-xl bg-base-200"
		>
			{#if track.cover_url && !imgError}
				<img
					src={track.cover_url}
					alt={track.album_name || track.title}
					class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
					loading="lazy"
					onerror={() => {
						imgError = true;
					}}
				/>
			{:else}
				<div class="flex h-full w-full items-center justify-center">
					<Disc3 class="h-10 w-10 text-base-content/20" />
				</div>
			{/if}

			{#if track.duration_ms}
				<span
					class="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px]
					font-medium text-white/90 backdrop-blur-sm"
				>
					{formatDuration(track.duration_ms)}
				</span>
			{/if}
		</a>
	{:else}
		<div class="relative aspect-square w-full overflow-hidden rounded-t-xl bg-base-200">
			{#if track.cover_url && !imgError}
				<img
					src={track.cover_url}
					alt={track.album_name || track.title}
					class="h-full w-full object-cover"
					loading="lazy"
					onerror={() => {
						imgError = true;
					}}
				/>
			{:else}
				<div class="flex h-full w-full items-center justify-center">
					<Disc3 class="h-10 w-10 text-base-content/20" />
				</div>
			{/if}

			{#if track.duration_ms}
				<span
					class="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px]
					font-medium text-white/90 backdrop-blur-sm"
				>
					{formatDuration(track.duration_ms)}
				</span>
			{/if}
		</div>
	{/if}

	<div class="flex flex-1 flex-col gap-0.5 p-2.5 pb-1.5">
		<h3 class="text-sm font-semibold leading-tight line-clamp-1 text-base-content">
			{track.title}
		</h3>
		{#if artistHref}
			<a
				href={artistHref}
				class="text-xs text-base-content/60 line-clamp-1 hover:text-primary transition-colors"
			>
				{track.artist_name}
			</a>
		{:else}
			<p class="text-xs text-base-content/60 line-clamp-1">{track.artist_name}</p>
		{/if}
		{#if track.album_name}
			{#if albumHref}
				<a
					href={albumHref}
					class="text-[11px] text-base-content/40 line-clamp-1 flex items-center gap-1
						hover:text-primary transition-colors"
				>
					<Music2 class="h-2.5 w-2.5 shrink-0" />
					{track.album_name}
				</a>
			{:else}
				<p class="text-[11px] text-base-content/40 line-clamp-1 flex items-center gap-1">
					<Music2 class="h-2.5 w-2.5 shrink-0" />
					{track.album_name}
				</p>
			{/if}
		{/if}
	</div>

	<div class="mt-auto flex items-center justify-center gap-3 px-2 pb-1 pt-0.5">
		{#if albumMbid && $integrationStore.download_client && !isRequested}
			<AlbumRequestButton
				mbid={albumMbid}
				artistName={track.artist_name}
				albumName={track.album_name || track.title}
				artistMbid={track.artist_mbid ?? undefined}
			/>
		{/if}
		<TrackPreviewButton
			artist={track.artist_name}
			track={track.title}
			{ytConfigured}
			{initialCached}
			size="md"
			albumId={track.release_group_mbid || track.recording_mbid || `rec-${index}`}
			coverUrl={track.cover_url}
			artistId={track.artist_mbid ?? undefined}
		/>
	</div>

	{#if showQuota && quotaInfo}
		<div class="px-2 pb-2 text-center">
			<span class="text-[10px] text-base-content/35">
				{quotaInfo.used}/{quotaInfo.limit} used today
			</span>
		</div>
	{:else}
		<div class="pb-1.5"></div>
	{/if}
</div>
