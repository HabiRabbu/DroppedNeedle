<script lang="ts">
	import type { SourcePlaylistSummary } from '$lib/types';
	import type { Snippet } from 'svelte';
	import { Disc3, ChevronRight, CheckCircle2, ArrowRight } from 'lucide-svelte';
	import { reveal } from '$lib/actions/reveal';

	interface Props {
		playlists: SourcePlaylistSummary[];
		sourceLabel: string;
		playlistsHref: string;
		sourceIcon: Snippet;
	}

	let { playlists, sourceLabel, playlistsHref, sourceIcon }: Props = $props();

	let totalCount = $derived(playlists.length);
	let importedCount = $derived(playlists.filter((p) => p.is_imported).length);
	let allImported = $derived(totalCount > 0 && importedCount === totalCount);
	let noneImported = $derived(importedCount === 0);

	let coverUrls = $derived(
		playlists
			.slice(0, 4)
			.map((p) => p.cover_url)
			.filter(Boolean)
	);

	let progressPct = $derived(totalCount > 0 ? (importedCount / totalCount) * 100 : 0);

	const RING_RADIUS = 28;
	const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
	let strokeDashoffset = $derived(RING_CIRCUMFERENCE - (progressPct / 100) * RING_CIRCUMFERENCE);

	let isHovered = $state(false);

	const fanAngles = [-8, -3, 3, 8];
	const fanOffsets = [-12, -4, 4, 12];
</script>

{#if totalCount > 0}
	<div use:reveal>
		<a
			href={playlistsHref}
			class="group relative flex w-full overflow-hidden rounded-2xl border border-base-content/5 bg-base-200/30 p-5 backdrop-blur-md transition-all duration-300 hover:border-base-content/10 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-base-100 sm:p-6"
			onpointerenter={() => (isHovered = true)}
			onpointerleave={() => (isHovered = false)}
		>
			<div
				class="pointer-events-none absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/[0.04] via-transparent to-secondary/[0.04]"
			></div>

			<div class="relative mr-6 hidden h-28 w-36 shrink-0 items-center justify-center sm:flex">
				{#if coverUrls.length > 0}
					{#each coverUrls as url, i (url)}
						{@const angle = fanAngles[i] ?? 0}
						{@const offset = fanOffsets[i] ?? 0}
						<div
							class="absolute h-20 w-20 overflow-hidden rounded-xl border-2 border-base-100 shadow-md transition-all duration-500"
							style="
								transform: rotate({isHovered ? angle * 1.4 : angle}deg) translateX({isHovered
								? offset * 1.3
								: offset}px);
								z-index: {i};
							"
						>
							<img src={url} alt="" class="h-full w-full object-cover" loading="lazy" />
						</div>
					{/each}
				{:else}
					{#each [0, 1, 2] as i (i)}
						{@const angle = [-6, 0, 6][i]}
						<div
							class="absolute flex h-20 w-20 items-center justify-center overflow-hidden rounded-xl border-2 border-base-100 bg-base-200 shadow-md transition-all duration-500"
							style="
								transform: rotate({isHovered ? angle * 1.4 : angle}deg);
								z-index: {i};
							"
						>
							<Disc3 class="h-8 w-8 text-base-content/20" />
						</div>
					{/each}
				{/if}
			</div>

			<div class="flex min-w-0 flex-1 items-center gap-4 sm:gap-5">
				<div class="min-w-0 flex-1">
					<div class="mb-1.5 flex items-center gap-1.5">
						{@render sourceIcon()}
						<span class="text-xs font-medium uppercase tracking-wider text-base-content/50"
							>{sourceLabel}</span
						>
					</div>

					{#if allImported}
						<h3 class="text-lg font-bold leading-tight sm:text-xl">
							All {totalCount} playlists imported!
						</h3>
						<p class="mt-1 text-sm text-base-content/50">
							Your {sourceLabel} playlists are now in DroppedNeedle.
						</p>
					{:else}
						<h3 class="text-lg font-bold leading-tight sm:text-xl">
							Bring your {totalCount}
							{sourceLabel} playlist{totalCount === 1 ? '' : 's'} to DroppedNeedle
						</h3>
						<p class="mt-1 text-sm text-base-content/50">
							{#if noneImported}
								Browse and import your playlists in one click.
							{:else}
								{importedCount} of {totalCount} imported so far.
							{/if}
						</p>
					{/if}
				</div>

				<div class="relative shrink-0">
					<svg class="h-16 w-16 -rotate-90 sm:h-[72px] sm:w-[72px]" viewBox="0 0 64 64" fill="none">
						<circle
							cx="32"
							cy="32"
							r={RING_RADIUS}
							stroke="currentColor"
							stroke-width="4"
							class="text-base-content/10"
						/>
						<circle
							cx="32"
							cy="32"
							r={RING_RADIUS}
							stroke="currentColor"
							stroke-width="4"
							stroke-linecap="round"
							stroke-dasharray={RING_CIRCUMFERENCE}
							stroke-dashoffset={strokeDashoffset}
							class="transition-all duration-700 {allImported ? 'text-success' : 'text-primary'}"
						/>
					</svg>
					<div class="absolute inset-0 flex items-center justify-center">
						{#if allImported}
							<CheckCircle2 class="h-6 w-6 text-success" />
						{:else}
							<span class="text-xs font-bold tabular-nums text-base-content/70">
								{importedCount}/{totalCount}
							</span>
						{/if}
					</div>
				</div>

				<div class="hidden shrink-0 sm:flex">
					<div
						class="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 transition-all duration-300 group-hover:bg-primary/20 group-hover:scale-110"
					>
						{#if allImported}
							<ArrowRight
								class="h-5 w-5 text-primary transition-transform duration-300 group-hover:translate-x-0.5"
							/>
						{:else}
							<ChevronRight
								class="h-5 w-5 text-primary transition-transform duration-300 group-hover:translate-x-0.5"
							/>
						{/if}
					</div>
				</div>
			</div>
		</a>
	</div>
{/if}
