<script lang="ts">
	import type { Artist } from '$lib/types';
	import { artistHref } from '$lib/utils/entityRoutes';
	import ArtistImage from './ArtistImage.svelte';
	import ArtistCardDownloadButton from './ArtistCardDownloadButton.svelte';

	interface Props {
		artist: Artist;
	}

	let { artist }: Props = $props();
</script>

<a
	href={artistHref(artist.musicbrainz_id)}
	class="card bg-base-100 w-full shadow-sm shrink-0 transition-all hover:scale-105 hover:glow-primary group relative"
	aria-label="Open {artist.title}"
>
	<ArtistCardDownloadButton artistName={artist.title} artistMbid={artist.musicbrainz_id} />
	<figure class="aspect-square p-3">
		<ArtistImage
			mbid={artist.musicbrainz_id}
			alt={artist.title}
			size="full"
			remoteUrl={artist.thumb_url ?? null}
			className="w-full h-full"
		/>
	</figure>

	<div class="card-body p-2 pt-0 items-center text-center">
		<h2 class="card-title text-xs line-clamp-1 min-h-[1.25rem]">{artist.title}</h2>
	</div>
</a>
