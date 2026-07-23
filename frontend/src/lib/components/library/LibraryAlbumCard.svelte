<script lang="ts">
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import LibraryFormatBadge from './LibraryFormatBadge.svelte';
	import LocalIdentityBadge from './LocalIdentityBadge.svelte';
	import type { LibraryAlbumSummary } from '$lib/types';
	import { albumHref } from '$lib/utils/entityRoutes';

	interface Props {
		album: LibraryAlbumSummary;
	}

	let { album }: Props = $props();
	let href = $derived(albumHref(album.musicbrainz_release_group_id ?? album.id));
</script>

<div
	class="card bg-base-100 w-full shadow-sm shrink-0 group relative transition-all hover:scale-105 hover:glow-primary"
>
	<a {href} class="block h-full" aria-label="Open {album.title}">
		<figure class="aspect-square overflow-hidden relative">
			<AlbumImage
				mbid={album.id}
				source="local"
				available={album.cover_available}
				alt={album.title}
				size="full"
				rounded="none"
				className="w-full h-full"
			/>
			<div class="absolute top-2 right-2 z-10">
				<LibraryFormatBadge format={album.format} />
			</div>
			{#if album.album_identity_state === 'local_only'}
				<LocalIdentityBadge
					state={album.album_identity_state}
					subject="album"
					compact
					className="absolute left-2 top-2 z-10"
				/>
			{/if}
		</figure>

		<div class="card-body p-3">
			<h2 class="card-title text-sm line-clamp-2 min-h-[2.5rem]">{album.title}</h2>
			<p class="text-xs opacity-70 line-clamp-1">
				{#if album.year}{album.year}{:else}Unknown{/if}
				{#if album.artist_name}
					<span class="opacity-50 mx-1">•</span>{album.artist_name}
				{/if}
			</p>
			<p class="text-[11px] opacity-50">
				{album.track_count}
				{album.track_count === 1 ? 'track' : 'tracks'}
			</p>
		</div>
	</a>
</div>
