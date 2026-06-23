<script lang="ts">
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import LibraryFormatBadge from './LibraryFormatBadge.svelte';
	import { albumHref } from '$lib/utils/entityRoutes';
	import type { LibraryAlbumSummary } from '$lib/types';

	interface Props {
		album: LibraryAlbumSummary;
	}

	let { album }: Props = $props();
</script>

<div
	class="card bg-base-100 w-full shadow-sm shrink-0 group relative transition-all hover:scale-105 hover:glow-primary"
>
	<a
		href={albumHref(album.release_group_mbid)}
		class="block h-full"
		aria-label="Open {album.album_title}"
	>
		<figure class="aspect-square overflow-hidden relative">
			<AlbumImage
				mbid={album.release_group_mbid}
				remoteUrl={album.cover_url}
				alt={album.album_title}
				size="full"
				rounded="none"
				className="w-full h-full"
			/>
			<div class="absolute top-2 right-2 z-10">
				<LibraryFormatBadge format={album.quality_format} />
			</div>
		</figure>

		<div class="card-body p-3">
			<h2 class="card-title text-sm line-clamp-2 min-h-[2.5rem]">{album.album_title}</h2>
			<p class="text-xs opacity-70 line-clamp-1">
				{#if album.year}{album.year}{:else}Unknown{/if}
				{#if album.album_artist_name}
					<span class="opacity-50 mx-1">•</span>{album.album_artist_name}
				{/if}
			</p>
			<p class="text-[11px] opacity-50">
				{album.track_count}
				{album.track_count === 1 ? 'track' : 'tracks'}
			</p>
		</div>
	</a>
</div>
