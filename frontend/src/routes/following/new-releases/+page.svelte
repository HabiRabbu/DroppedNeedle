<script lang="ts">
	import { onMount } from 'svelte';
	import { Disc3, Plus, Check, ArrowLeft } from 'lucide-svelte';
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { getNewReleasesQuery } from '$lib/queries/following/FollowQueries.svelte';
	import { createMarkNewReleasesSeenMutation } from '$lib/queries/following/FollowMutations.svelte';
	import { requestAlbum } from '$lib/queries/downloads/DownloadMutations.svelte';
	import type { NewRelease } from '$lib/queries/following/types';
	import { SvelteSet } from 'svelte/reactivity';

	const PAGE = 48;
	let limit = $state(PAGE);
	const query = getNewReleasesQuery(
		() => limit,
		() => 0
	);
	const items = $derived(query.data?.items ?? []);
	const total = $derived(query.data?.total ?? 0);

	const request = requestAlbum();
	let requested = new SvelteSet<string>();

	// visiting this page is what clears the sidebar new-releases badge
	const markSeen = createMarkNewReleasesSeenMutation();
	onMount(() => markSeen.mutate(undefined));

	function onRequest(item: NewRelease) {
		request.mutate({
			release_group_mbid: item.release_group_mbid,
			artist_name: item.artist_name,
			album_title: item.title,
			artist_mbid: item.artist_mbid
		});
		requested.add(item.release_group_mbid);
	}
</script>

<svelte:head>
	<title>New Releases - DroppedNeedle</title>
</svelte:head>

<div class="mx-auto w-full max-w-6xl px-2 py-4 sm:px-4 sm:py-8 lg:px-8">
	<div class="mb-6 flex items-center gap-3">
		<a href="/following" class="btn btn-ghost btn-sm btn-circle" aria-label="Back to Following">
			<ArrowLeft class="h-5 w-5" />
		</a>
		<Disc3 class="h-6 w-6 text-primary" aria-hidden="true" />
		<h1 class="text-2xl font-bold sm:text-3xl">New Releases</h1>
	</div>

	{#if query.isPending}
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
			{#each Array(10) as _, i (i)}
				<div class="aspect-square w-full animate-pulse rounded-2xl bg-base-200"></div>
			{/each}
		</div>
	{:else if items.length === 0}
		<EmptyState
			icon={Disc3}
			title="No new releases yet"
			description="When an artist you follow puts out something new, it shows up here."
			ctaLabel="Your Artists"
			ctaHref="/following/artists"
		/>
	{:else}
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
			{#each items as item (item.release_group_mbid)}
				{@const isRequested = requested.has(item.release_group_mbid)}
				<div class="group flex flex-col gap-2">
					<a
						href="/album/{item.release_group_mbid}"
						class="overflow-hidden rounded-2xl"
						aria-label="Open {item.title}"
					>
						<AlbumImage
							mbid={item.release_group_mbid}
							alt={item.title}
							size="md"
							rounded="xl"
							className="w-full aspect-square transition-transform duration-300 group-hover:scale-105"
						/>
					</a>
					<a href="/album/{item.release_group_mbid}" class="truncate font-semibold hover:underline">
						{item.title}
					</a>
					<a
						href="/artist/{item.artist_mbid}"
						class="truncate text-sm text-base-content/70 hover:underline"
					>
						{item.artist_name}
					</a>
					<div class="flex items-center justify-between gap-2">
						{#if item.first_release_date}
							<span class="text-xs text-base-content/50 tabular-nums"
								>{item.first_release_date}</span
							>
						{:else}
							<span></span>
						{/if}
						<button
							class="btn btn-xs gap-1 {isRequested ? 'btn-success btn-outline' : 'btn-accent'}"
							onclick={() => onRequest(item)}
							disabled={isRequested}
						>
							{#if isRequested}
								<Check class="h-3.5 w-3.5" /> Requested
							{:else}
								<Plus class="h-3.5 w-3.5" /> Request
							{/if}
						</button>
					</div>
				</div>
			{/each}
		</div>

		{#if items.length < total}
			<div class="mt-6 flex justify-center">
				<button class="btn btn-outline" onclick={() => (limit += PAGE)} disabled={query.isFetching}>
					{query.isFetching ? 'Loading...' : `Load more (${total - items.length} more)`}
				</button>
			</div>
		{/if}
	{/if}
</div>
