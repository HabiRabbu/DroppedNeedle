<script lang="ts">
	import { Check } from 'lucide-svelte';
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import AlbumCardOverlay from '$lib/components/AlbumCardOverlay.svelte';
	import type { HomeAlbum } from '$lib/types';

	interface Props {
		album: HomeAlbum;
		showLibraryBadge?: boolean;
		onclick?: () => void;
		href?: string | null;
	}

	let { album, showLibraryBadge = false, onclick, href = null }: Props = $props();
</script>

<svelte:element
	this={href ? 'a' : 'button'}
	href={href ?? undefined}
	type={href ? undefined : 'button'}
	onclick={href ? undefined : onclick}
	onkeydown={href || !onclick ? undefined : (e: KeyboardEvent) => e.key === 'Enter' && onclick()}
	role={href || !onclick ? undefined : 'button'}
	tabindex={href || !onclick ? undefined : 0}
	class="card bg-base-200/50 hover:bg-base-200 hover:scale-[1.03] hover:shadow-lg transition-all duration-200 group {href ||
	onclick
		? 'cursor-pointer'
		: 'cursor-default'}"
>
	<figure class="aspect-square overflow-hidden relative rounded-t-2xl">
		<AlbumImage
			mbid={album.mbid || ''}
			alt={album.name}
			size="md"
			rounded="none"
			className="w-full h-full"
			customUrl={album.image_url || null}
		/>
		{#if showLibraryBadge || album.in_library}
			<div class="absolute top-2 left-2 z-20 badge badge-success badge-sm gap-1 opacity-90">
				<Check class="w-3 h-3" />
			</div>
		{/if}
		{#if album.mbid && album.in_library}
			<AlbumCardOverlay
				mbid={album.mbid}
				albumName={album.name}
				artistName={album.artist_name || 'Unknown'}
				coverUrl={album.image_url || null}
			/>
		{/if}
	</figure>
	<div class="card-body p-3">
		<h3 class="font-semibold text-sm line-clamp-1">{album.name}</h3>
		<p class="text-xs text-base-content/50 line-clamp-1">
			{album.artist_name || 'Unknown Artist'}
			{#if album.release_date}
				· {album.release_date}
			{/if}
		</p>
	</div>
</svelte:element>
