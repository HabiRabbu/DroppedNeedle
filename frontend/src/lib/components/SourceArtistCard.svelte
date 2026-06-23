<script lang="ts">
	import ArtistImage from './ArtistImage.svelte';
	import ArtistCardDownloadButton from './ArtistCardDownloadButton.svelte';
	import { Users } from 'lucide-svelte';

	interface Props {
		name: string;
		imageUrl?: string | null;
		mbid?: string | null;
		href?: string;
		albumCount?: number;
	}

	let { name, imageUrl = null, mbid = null, href, albumCount }: Props = $props();
</script>

{#if href}
	<a
		{href}
		class="card bg-base-100 w-full shadow-sm shrink-0 transition-all hover:scale-105 hover:glow-primary focus-visible:ring-2 focus-visible:ring-primary group relative"
		aria-label="Open {name}"
	>
		{#if mbid}
			<ArtistCardDownloadButton artistName={name} artistMbid={mbid} />
		{/if}
		<figure class="aspect-square p-3">
			{#if mbid}
				<ArtistImage {mbid} alt={name} size="full" remoteUrl={imageUrl} className="w-full h-full" />
			{:else if imageUrl}
				<img
					src={imageUrl}
					alt={name}
					class="w-full h-full rounded-full object-cover"
					loading="lazy"
				/>
			{:else}
				<div
					class="flex h-full w-full items-center justify-center rounded-full bg-base-200 text-base-content/20"
				>
					<Users class="h-12 w-12" />
				</div>
			{/if}
		</figure>
		<div class="card-body p-2 pt-0 items-center text-center">
			<h2 class="card-title text-xs line-clamp-1 min-h-[1.25rem]">{name}</h2>
			{#if albumCount !== undefined}
				<p class="text-xs text-base-content/50">{albumCount} album{albumCount !== 1 ? 's' : ''}</p>
			{/if}
		</div>
	</a>
{:else}
	<div class="card bg-base-100 w-full shadow-sm shrink-0">
		<figure class="aspect-square p-3">
			{#if mbid}
				<ArtistImage {mbid} alt={name} size="full" remoteUrl={imageUrl} className="w-full h-full" />
			{:else if imageUrl}
				<img
					src={imageUrl}
					alt={name}
					class="w-full h-full rounded-full object-cover"
					loading="lazy"
				/>
			{:else}
				<div
					class="flex h-full w-full items-center justify-center rounded-full bg-base-200 text-base-content/20"
				>
					<Users class="h-12 w-12" />
				</div>
			{/if}
		</figure>
		<div class="card-body p-2 pt-0 items-center text-center">
			<h2 class="card-title text-xs line-clamp-1 min-h-[1.25rem]">{name}</h2>
			{#if albumCount !== undefined}
				<p class="text-xs text-base-content/50">{albumCount} album{albumCount !== 1 ? 's' : ''}</p>
			{/if}
		</div>
	</div>
{/if}
