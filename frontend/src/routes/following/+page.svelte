<script lang="ts">
	import { Heart, Disc3, CalendarClock, ArrowRight } from 'lucide-svelte';
	import {
		getFollowedArtistsQuery,
		getNewReleasesQuery
	} from '$lib/queries/following/FollowQueries.svelte';

	const artistsQuery = getFollowedArtistsQuery();
	const newReleasesQuery = getNewReleasesQuery(
		() => 1,
		() => 0
	);

	const artistCount = $derived(artistsQuery.data?.length ?? 0);
	const newReleaseCount = $derived(newReleasesQuery.data?.total ?? 0);
	const loading = $derived(artistsQuery.isPending || newReleasesQuery.isPending);
</script>

<svelte:head>
	<title>Following - DroppedNeedle</title>
</svelte:head>

<div class="mx-auto w-full max-w-5xl px-2 py-4 sm:px-4 sm:py-8 lg:px-8">
	<div class="mb-6 flex items-center gap-2">
		<Heart class="h-6 w-6 text-primary" aria-hidden="true" />
		<h1 class="text-2xl font-bold sm:text-3xl">Following</h1>
	</div>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<a
			href="/following/artists"
			class="hub-tile group"
			aria-label="Your followed artists ({artistCount})"
		>
			<span class="hub-icon"><Heart class="h-6 w-6" aria-hidden="true" /></span>
			<span class="hub-count">{loading ? '–' : artistCount}</span>
			<span class="hub-label">
				Your Artists
				<ArrowRight
					class="h-4 w-4 -translate-x-1 opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100"
					aria-hidden="true"
				/>
			</span>
		</a>

		<a
			href="/following/new-releases"
			class="hub-tile group"
			aria-label="New releases ({newReleaseCount} new)"
		>
			<span class="hub-icon"><Disc3 class="h-6 w-6" aria-hidden="true" /></span>
			<span class="hub-count">{loading ? '–' : `${newReleaseCount} new`}</span>
			<span class="hub-label">
				New Releases
				<ArrowRight
					class="h-4 w-4 -translate-x-1 opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100"
					aria-hidden="true"
				/>
			</span>
		</a>

		<div class="hub-tile hub-tile-soon sm:col-span-2" aria-disabled="true">
			<span class="hub-icon hub-icon-muted">
				<CalendarClock class="h-6 w-6" aria-hidden="true" />
			</span>
			<span class="hub-label text-base-content/50">Events &amp; news - coming soon</span>
		</div>
	</div>
</div>

<style>
	.hub-tile {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		border-radius: 1rem;
		border: 1px solid var(--color-base-300);
		background-color: var(--color-base-200);
		padding: 1.5rem;
		transition:
			transform 0.25s ease,
			border-color 0.25s ease,
			box-shadow 0.25s ease;
	}
	.hub-tile:not(.hub-tile-soon):hover {
		transform: translateY(-2px);
		border-color: var(--color-primary);
		box-shadow: 0 10px 30px -12px oklch(from var(--color-primary) l c h / 0.45);
	}
	.hub-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 3rem;
		height: 3rem;
		border-radius: 9999px;
		background-color: oklch(from var(--color-primary) l c h / 0.15);
		color: var(--color-primary);
	}
	.hub-icon-muted {
		background-color: var(--color-base-300);
		color: var(--color-base-content);
		opacity: 0.5;
	}
	.hub-count {
		font-size: 2.25rem;
		line-height: 1;
		font-weight: 700;
		color: var(--color-primary);
		font-variant-numeric: tabular-nums;
	}
	.hub-label {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		font-weight: 600;
	}
	.hub-tile-soon {
		flex-direction: row;
		align-items: center;
		border-style: dashed;
		background-color: transparent;
	}
</style>
