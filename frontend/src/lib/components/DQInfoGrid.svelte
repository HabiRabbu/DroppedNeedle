<script lang="ts">
	import { Calendar, Globe, Volume2, CircleCheck } from 'lucide-svelte';
	import type { DiscoverQueueEnrichment } from '$lib/types';
	import { countryToFlag } from '$lib/utils/formatting';

	interface Props {
		enrichment: DiscoverQueueEnrichment;
		inLibrary?: boolean;
		showTags?: boolean;
	}

	let { enrichment, inLibrary = false, showTags = true }: Props = $props();
</script>

<div class="flex flex-col gap-2">
	{#if enrichment.release_date}
		<div class="flex items-center gap-2 text-xs text-base-content/60">
			<span class="w-5 text-center shrink-0 text-base-content/40">
				<Calendar class="w-4 h-4" />
			</span>
			<div class="flex flex-col gap-px">
				<span class="text-[0.6rem] uppercase tracking-wider font-bold text-base-content/35">
					Released
				</span>
				<span class="text-sm font-semibold text-base-content/80">{enrichment.release_date}</span>
			</div>
		</div>
	{/if}
	{#if enrichment.country}
		<div class="flex items-center gap-2 text-xs text-base-content/60">
			<span class="w-5 text-center shrink-0 text-base-content/40">
				<Globe class="w-4 h-4" />
			</span>
			<div class="flex flex-col gap-px">
				<span class="text-[0.6rem] uppercase tracking-wider font-bold text-base-content/35">
					Origin
				</span>
				<span class="text-sm font-semibold text-base-content/80">
					{countryToFlag(enrichment.country)}
					{enrichment.country}
				</span>
			</div>
		</div>
	{/if}
	{#if enrichment.listen_count != null}
		<div class="flex items-center gap-2 text-xs text-base-content/60">
			<span class="w-5 text-center shrink-0 text-base-content/40">
				<Volume2 class="w-4 h-4" />
			</span>
			<div class="flex flex-col gap-px">
				<span class="text-[0.6rem] uppercase tracking-wider font-bold text-base-content/35">
					Plays
				</span>
				<span class="text-sm font-semibold text-base-content/80">
					{enrichment.listen_count.toLocaleString()}
				</span>
			</div>
		</div>
	{/if}
	{#if inLibrary}
		<div class="flex items-center gap-2 text-xs text-base-content/60">
			<span class="w-5 text-center shrink-0 text-base-content/40">
				<CircleCheck class="w-4 h-4 text-success" />
			</span>
			<div class="flex flex-col gap-px">
				<span class="text-[0.6rem] uppercase tracking-wider font-bold text-base-content/35">
					Library
				</span>
				<span class="text-sm font-semibold text-success">In Library</span>
			</div>
		</div>
	{/if}
</div>
{#if showTags && enrichment.tags.length > 0}
	<div class="flex flex-wrap gap-1 mt-2">
		{#each enrichment.tags.slice(0, 6) as tag, i (`tag-${i}`)}
			<span class="dq-tag">{tag}</span>
		{/each}
	</div>
{/if}

<style>
	.dq-tag {
		font-size: 0.75rem;
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		background: color-mix(in srgb, var(--color-base-100) 5%, transparent);
		backdrop-filter: blur(8px);
		color: color-mix(in srgb, var(--color-base-content) 80%, transparent);
		font-family: var(--font-mono);
		font-weight: 400;
		border: 1px solid color-mix(in srgb, var(--color-base-content) 10%, transparent);
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
		transition: all 0.2s ease;
	}

	.dq-tag:hover {
		border-color: color-mix(in srgb, var(--color-base-content) 30%, transparent);
		background: color-mix(in srgb, var(--color-base-100) 10%, transparent);
	}
</style>
