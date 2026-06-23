<script lang="ts">
	import { run } from 'svelte/legacy';

	import { Check, RefreshCw } from 'lucide-svelte';
	import type { ArtistInfo } from '$lib/types';
	import { extractDominantColor, DEFAULT_GRADIENT } from '$lib/utils/colors';
	import { appendAudioDBSizeSuffix } from '$lib/utils/imageSuffix';
	import { imageSettingsStore } from '$lib/stores/imageSettings';
	import ArtistLinks from './ArtistLinks.svelte';
	import FollowControl from './FollowControl.svelte';
	import BackButton from './BackButton.svelte';
	import HeroBackdrop from './HeroBackdrop.svelte';
	import { getApiUrl } from '$lib/api/api-utils';

	interface Props {
		artist: ArtistInfo;
		showBackButton?: boolean;
		refreshing?: boolean;
		onrefresh?: () => void;
	}

	let { artist, showBackButton = false, refreshing = false, onrefresh }: Props = $props();

	let heroGradient = $state(DEFAULT_GRADIENT);
	let heroImageLoaded = $state(false);
	let avatarRemoteError = $state(false);

	let useRemoteAvatar = $derived(artist.thumb_url && $imageSettingsStore.directRemoteImagesEnabled);
	let resolvedRemoteAvatar = $derived(
		artist.thumb_url ? appendAudioDBSizeSuffix(artist.thumb_url, 'hero') : null
	);
	run(() => {
		if (artist.musicbrainz_id) {
			avatarRemoteError = false;
		}
	});

	let resolvedBackdropUrl = $derived.by(() => {
		if ($imageSettingsStore.directRemoteImagesEnabled) {
			if (artist.banner_url) return artist.banner_url;
			if (artist.wide_thumb_url) return artist.wide_thumb_url;
			if (artist.fanart_url) return artist.fanart_url;
		}
		if (heroImageLoaded)
			return getApiUrl(`/api/v1/covers/artist/${artist.musicbrainz_id}?size=500`);
		return null;
	});

	let hasDistinctBackdrop = $derived(
		$imageSettingsStore.directRemoteImagesEnabled &&
			!!(artist.banner_url || artist.wide_thumb_url || artist.fanart_url)
	);

	function onHeroImageLoad() {
		heroImageLoaded = true;
		extractDominantColor(getApiUrl(`/api/v1/covers/artist/${artist.musicbrainz_id}?size=250`)).then(
			(gradient) => (heroGradient = gradient)
		);
	}

	let validLinks = $derived(
		artist.external_links.filter((link) => link.url && link.url.trim() !== '')
	);
</script>

<div
	class="artist-hero group relative -mx-2 sm:-mx-4 lg:-mx-8 -mt-4 sm:-mt-8 overflow-hidden rounded-2xl transition-all duration-500"
>
	<div class="absolute inset-0 bg-gradient-to-b {heroGradient} transition-all duration-1000"></div>

	<HeroBackdrop
		imageUrl={resolvedBackdropUrl}
		opacity={hasDistinctBackdrop ? 0.25 : 0.16}
		hoverOpacity={hasDistinctBackdrop ? 0.35 : 0.22}
		blur={hasDistinctBackdrop ? 0 : 2}
		hoverBlur={0}
		position="full"
	/>

	<div class="relative z-10 px-4 sm:px-8 lg:px-12 pt-6 pb-8 sm:pt-8 sm:pb-12">
		{#if onrefresh && artist.in_library}
			<button
				class="absolute top-3 right-3 btn btn-sm btn-ghost btn-circle z-20"
				onclick={onrefresh}
				disabled={refreshing}
				title="Refresh artist info"
			>
				<RefreshCw class="h-5 w-5 {refreshing ? 'animate-spin' : ''}" />
			</button>
		{/if}
		<div class="max-w-7xl mx-auto">
			{#if showBackButton}
				<div class="mb-4">
					<BackButton />
				</div>
			{/if}
			<div class="flex flex-col sm:flex-row items-center sm:items-end gap-6 sm:gap-8">
				<div class="shrink-0">
					<div class="relative">
						<div
							class="w-40 h-40 sm:w-52 sm:h-52 lg:w-64 lg:h-64 rounded-full overflow-hidden shadow-2xl ring-4 ring-base-100/20 bg-neutral"
						>
							{#if !heroImageLoaded}
								<div class="absolute inset-0 flex items-center justify-center">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 200 200"
										class="w-full h-full"
									>
										<rect fill="var(--color-neutral)" width="200" height="200" />
										<circle cx="100" cy="80" r="30" fill="var(--color-neutral-content)" />
										<path
											d="M60 120 Q100 140 140 120 L140 160 Q100 180 60 160 Z"
											fill="var(--color-neutral-content)"
										/>
									</svg>
								</div>
							{/if}
							{#if useRemoteAvatar && resolvedRemoteAvatar && !avatarRemoteError}
								<img
									src={resolvedRemoteAvatar}
									alt={artist.name}
									class="w-full h-full object-cover transition-opacity duration-300 {heroImageLoaded
										? 'opacity-100'
										: 'opacity-0'}"
									loading="lazy"
									decoding="async"
									referrerpolicy="no-referrer"
									onload={onHeroImageLoad}
									onerror={() => {
										avatarRemoteError = true;
										heroImageLoaded = false;
									}}
								/>
							{:else}
								<img
									src={getApiUrl(`/api/v1/covers/artist/${artist.musicbrainz_id}?size=500`)}
									alt={artist.name}
									class="w-full h-full object-cover transition-opacity duration-300 {heroImageLoaded
										? 'opacity-100'
										: 'opacity-0'}"
									loading="lazy"
									decoding="async"
									onload={onHeroImageLoad}
									onerror={(e) => {
										const target = e.currentTarget as HTMLImageElement;
										target.style.display = 'none';
									}}
								/>
							{/if}
						</div>
						{#if artist.in_library}
							<div class="absolute -bottom-2 -right-2 badge badge-success badge-lg gap-1 shadow-lg">
								<Check class="h-4 w-4" />
								In Library
							</div>
						{/if}
					</div>
				</div>

				<div class="flex-1 text-center sm:text-left min-w-0">
					{#if artist.type}
						<span
							class="text-xs sm:text-sm font-medium text-base-content/70 uppercase tracking-wider"
						>
							{artist.type === 'Group' ? 'Band' : artist.type === 'Person' ? 'Artist' : artist.type}
						</span>
					{/if}
					<h1
						class="hero-title text-3xl sm:text-4xl lg:text-5xl xl:text-6xl font-bold text-base-content mt-1 mb-2 break-words"
					>
						{artist.name}
					</h1>
					{#if artist.disambiguation}
						<p class="text-base-content/60 text-sm sm:text-base mb-3">({artist.disambiguation})</p>
					{/if}

					{#if validLinks.length > 0}
						<ArtistLinks links={validLinks} />
					{/if}

					<div class="mt-3">
						<FollowControl artistMbid={artist.musicbrainz_id} />
					</div>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	.artist-hero {
		--hero-glow-color: var(--brand-hero);
		border: 1px solid rgb(var(--brand-hero) / 0.08);
		animation: hero-glow 4s ease-in-out infinite;
	}
	.artist-hero:hover {
		border-color: rgb(var(--brand-hero) / 0.2);
	}
	@media (prefers-reduced-motion: reduce) {
		.artist-hero {
			animation: none;
		}
	}
</style>
