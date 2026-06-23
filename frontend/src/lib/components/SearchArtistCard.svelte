<script lang="ts">
	import type { Artist, EnrichmentSource } from '$lib/types';
	import { artistHref } from '$lib/utils/entityRoutes';
	import { formatListenCount } from '$lib/utils/formatting';
	import { getListenTitle } from '$lib/utils/enrichment';
	import { Music2 } from 'lucide-svelte';
	import ArtistImage from './ArtistImage.svelte';
	import ArtistCardDownloadButton from './ArtistCardDownloadButton.svelte';

	interface Props {
		artist: Artist;
		enrichmentSource?: EnrichmentSource;
	}

	let { artist, enrichmentSource = 'none' }: Props = $props();

	let listenTitle = $derived(getListenTitle(enrichmentSource, 'artist'));
</script>

<a
	href={artistHref(artist.musicbrainz_id)}
	class="card bg-base-100 w-full shadow-sm shrink-0 cursor-pointer transition-all hover:scale-105 hover:glow-primary group relative"
>
	<ArtistCardDownloadButton artistName={artist.title} artistMbid={artist.musicbrainz_id} />
	<figure class="flex justify-center pt-4">
		<ArtistImage
			mbid={artist.musicbrainz_id}
			alt={artist.title}
			size="lg"
			remoteUrl={artist.thumb_url ?? null}
		/>
	</figure>

	<div class="card-body p-3 pt-2 items-center text-center gap-0.5">
		<h2 class="font-semibold text-sm line-clamp-1">{artist.title}</h2>

		<p class="text-xs text-base-content/60 line-clamp-1 min-h-[1rem]">
			{#if artist.disambiguation}{artist.disambiguation}{:else}&nbsp;{/if}
		</p>

		<div class="flex flex-wrap items-center justify-center gap-1 mt-1 min-h-[1.5rem]">
			{#if artist.release_group_count != null}
				<span class="badge badge-sm badge-ghost">
					{artist.release_group_count} release{artist.release_group_count !== 1 ? 's' : ''}
				</span>
			{/if}
			{#if artist.listen_count != null}
				{#if enrichmentSource === 'lastfm'}
					<span
						class="badge badge-sm border-0"
						style="background-color: rgb(var(--brand-lastfm) / 0.15); color: rgb(var(--brand-lastfm));"
						title={listenTitle}
					>
						Last.fm {formatListenCount(artist.listen_count, true)}
					</span>
				{:else if enrichmentSource === 'listenbrainz'}
					<span
						class="badge badge-sm border-0"
						style="background-color: rgb(var(--brand-listenbrainz) / 0.15); color: rgb(var(--brand-listenbrainz));"
						title={listenTitle}
					>
						LB {formatListenCount(artist.listen_count, true)}
					</span>
				{:else}
					<span class="badge badge-sm badge-ghost" title={listenTitle}>
						<Music2 class="inline h-3 w-3" />
						{formatListenCount(artist.listen_count, true)}
					</span>
				{/if}
			{/if}
		</div>
	</div>
</a>
