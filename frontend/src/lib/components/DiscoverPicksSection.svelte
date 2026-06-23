<script lang="ts">
	import type { HomeSection as HomeSectionType, HomeAlbum } from '$lib/types';
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import AlbumCardOverlay from '$lib/components/AlbumCardOverlay.svelte';
	import AlbumRequestButton from '$lib/components/AlbumRequestButton.svelte';
	import HorizontalCarousel from '$lib/components/HorizontalCarousel.svelte';
	import TrackPreviewButton from '$lib/components/TrackPreviewButton.svelte';
	import SourceBadge from '$lib/components/SourceBadge.svelte';
	import { Sparkles, Check, Search } from 'lucide-svelte';
	import { albumHrefOrNull } from '$lib/utils/entityRoutes';
	import { goto } from '$app/navigation';
	import { integrationStore } from '$lib/stores/integration';
	import { libraryStore } from '$lib/stores/library';

	interface Props {
		section: HomeSectionType;
	}

	let { section }: Props = $props();

	let albums = $derived(section.items as HomeAlbum[]);
	let heroAlbum = $derived(albums[0] ?? null);
	let remainingAlbums = $derived(albums.slice(1));

	function handleAlbumSearch(album: HomeAlbum) {
		const query = [album.artist_name, album.name].filter(Boolean).join(' ').trim();
		if (query) {
			goto(`/search/albums?q=${encodeURIComponent(query)}`);
		}
	}
</script>

{#if albums.length > 0}
	<section class="mb-6 sm:mb-8">
		<div
			class="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/8 via-base-200/50 to-secondary/8 p-5 sm:p-6 backdrop-blur-sm shadow-[0_4px_24px_oklch(from_var(--color-primary)_l_c_h/0.08)]"
		>
			<div class="mb-4 flex items-center gap-3">
				<div class="flex items-center gap-2">
					<span class="animate-glow-pulse rounded-lg p-1">
						<Sparkles class="h-5 w-5 text-primary" />
					</span>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-lg font-bold sm:text-xl">{section.title}</h2>
							<SourceBadge source={section.source ?? undefined} />
						</div>
						<p class="text-xs text-base-content/50">Picked for you</p>
					</div>
				</div>
			</div>

			<div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-5">
				{#if heroAlbum}
					{@const heroHref = albumHrefOrNull(heroAlbum.mbid)}
					<svelte:element
						this={heroHref ? 'a' : 'div'}
						href={heroHref ?? undefined}
						data-sveltekit-preload-data={heroHref ? 'hover' : undefined}
						class="group relative w-full shrink-0 overflow-hidden rounded-xl transition-all duration-300 lg:w-[200px] {heroHref
							? 'cursor-pointer motion-safe:hover:scale-[1.02] hover:shadow-[0_0_30px_oklch(from_var(--color-primary)_l_c_h/0.2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-base-100'
							: 'cursor-default'}"
					>
						<div
							class="animate-glow-pulse pointer-events-none absolute inset-0 z-10 rounded-xl"
						></div>

						<div class="relative aspect-square overflow-hidden rounded-xl">
							<AlbumImage
								mbid={heroAlbum.mbid || ''}
								alt={heroAlbum.name}
								size="md"
								rounded="none"
								className="w-full h-full"
								customUrl={heroAlbum.image_url || null}
							/>

							<div
								class="absolute right-2 top-2 z-20 flex items-center gap-1 rounded-md bg-primary/90 px-2 py-0.5 text-primary-content backdrop-blur-sm"
							>
								<Sparkles class="h-3 w-3" />
								<span class="text-[10px] font-semibold">Featured Pick</span>
							</div>

							{#if heroAlbum.in_library}
								<div class="absolute left-2 top-2 z-20 badge badge-success badge-sm">
									<Check class="h-3.5 w-3.5" />
								</div>
							{/if}

							{#if heroAlbum.mbid && heroAlbum.in_library}
								<AlbumCardOverlay
									mbid={heroAlbum.mbid}
									albumName={heroAlbum.name}
									artistName={heroAlbum.artist_name || 'Unknown'}
									coverUrl={heroAlbum.image_url || null}
									size="md"
								/>
							{/if}

							{#if !heroAlbum.mbid}
								<button
									type="button"
									class="btn btn-ghost btn-sm btn-circle absolute bottom-1 right-1 z-20 min-h-[44px] min-w-[44px]"
									title="Search album"
									aria-label="Search for {heroAlbum.name}"
									onclick={(e) => {
										e.stopPropagation();
										e.preventDefault();
										handleAlbumSearch(heroAlbum);
									}}
								>
									<Search class="h-4 w-4" />
								</button>
							{/if}

							<div
								class="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/70 to-transparent"
							></div>

							<div class="absolute inset-x-0 bottom-0 z-10 p-3">
								<h3 class="text-sm font-bold text-white line-clamp-1 drop-shadow-md">
									{heroAlbum.name}
								</h3>
								{#if heroAlbum.artist_name}
									<p class="text-xs text-white/75 line-clamp-1 drop-shadow-md">
										{heroAlbum.artist_name}
									</p>
								{/if}
							</div>
						</div>
					</svelte:element>
					{#if heroAlbum.mbid}
						<div class="flex items-center justify-center gap-2 mt-2">
							{#if $integrationStore.download_client && !heroAlbum.in_library && !(heroAlbum.requested || libraryStore.isRequested(heroAlbum.mbid))}
								<AlbumRequestButton
									mbid={heroAlbum.mbid}
									artistName={heroAlbum.artist_name ?? ''}
									albumName={heroAlbum.name}
									artistMbid={heroAlbum.artist_mbid ?? undefined}
								/>
							{/if}
							<TrackPreviewButton
								artist={heroAlbum.artist_name ?? ''}
								track={heroAlbum.name}
								ytConfigured={$integrationStore.youtube_api}
								size="sm"
								albumId={heroAlbum.mbid}
								coverUrl={heroAlbum.image_url}
								artistId={heroAlbum.artist_mbid ?? undefined}
							/>
						</div>
					{/if}
				{/if}

				{#if remainingAlbums.length > 0}
					<div class="min-w-0 flex-1">
						<HorizontalCarousel class="-mx-4 px-4 sm:mx-0 sm:px-0 pb-2">
							{#each remainingAlbums as album, i (`${album.name}-${i}`)}
								{@const albumHref = albumHrefOrNull(album.mbid)}
								<div class="w-32 shrink-0 sm:w-36 md:w-44">
									<svelte:element
										this={albumHref ? 'a' : 'div'}
										href={albumHref ?? undefined}
										class="card bg-base-100 w-full shadow-sm transition-all group {albumHref
											? 'cursor-pointer hover:scale-105 active:scale-95 hover:shadow-[0_0_20px_oklch(from_var(--color-primary)_l_c_h/0.15)]'
											: 'cursor-default opacity-90'}"
									>
										<figure class="aspect-square overflow-hidden relative">
											<AlbumImage
												mbid={album.mbid || ''}
												alt={album.name}
												size="md"
												rounded="none"
												className="w-full h-full"
												customUrl={album.image_url || null}
											/>
											{#if album.in_library}
												<div class="absolute top-2 left-2 z-20 badge badge-success badge-sm">
													<Check class="w-3.5 h-3.5" />
												</div>
											{/if}
											{#if album.mbid && album.in_library}
												<AlbumCardOverlay
													mbid={album.mbid}
													albumName={album.name}
													artistName={album.artist_name || 'Unknown'}
													coverUrl={album.image_url || null}
													size="sm"
												/>
											{/if}
											{#if !album.mbid}
												<button
													type="button"
													class="btn btn-ghost btn-sm btn-circle absolute bottom-1 right-1 min-h-[44px] min-w-[44px]"
													title="Search album"
													aria-label="Search for {album.name}"
													onclick={(e) => {
														e.stopPropagation();
														handleAlbumSearch(album);
													}}
												>
													<Search class="w-4 h-4" />
												</button>
											{/if}
										</figure>
										<div class="card-body p-2">
											<h3 class="card-title text-xs line-clamp-1">{album.name}</h3>
											{#if album.artist_name}
												<p class="text-xs text-base-content/50 line-clamp-1">
													{album.artist_name}
												</p>
											{/if}
										</div>
									</svelte:element>
									{#if album.mbid}
										{@const isAlbumRequested =
											album.requested || libraryStore.isRequested(album.mbid)}
										<div class="flex items-center justify-center gap-1 mt-1 pb-1">
											{#if $integrationStore.download_client && !album.in_library && !isAlbumRequested}
												<AlbumRequestButton
													mbid={album.mbid}
													artistName={album.artist_name ?? ''}
													albumName={album.name}
													artistMbid={album.artist_mbid ?? undefined}
												/>
											{/if}
											<TrackPreviewButton
												artist={album.artist_name ?? ''}
												track={album.name}
												ytConfigured={$integrationStore.youtube_api}
												size="sm"
												albumId={album.mbid}
												coverUrl={album.image_url}
												artistId={album.artist_mbid ?? undefined}
											/>
										</div>
									{/if}
								</div>
							{/each}
						</HorizontalCarousel>
					</div>
				{/if}
			</div>
		</div>
	</section>
{/if}
