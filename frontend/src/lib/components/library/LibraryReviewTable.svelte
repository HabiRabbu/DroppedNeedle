<script lang="ts">
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { ClipboardCheck } from 'lucide-svelte';
	import type { ReviewListItem } from '$lib/queries/library/LibraryOperationsTypes';
	import LibraryReviewCard from './LibraryReviewCard.svelte';

	interface Props {
		items: ReviewListItem[];
		selectedIds: string[];
		filtered: boolean;
		state?: string;
		rootLabels?: Record<string, string>;
		onselectionchange: (ids: string[]) => void;
		onreview: (id: string) => void;
	}
	let {
		items,
		selectedIds,
		filtered,
		state = undefined,
		rootLabels = {},
		onselectionchange,
		onreview
	}: Props = $props();

	function select(id: string, selected: boolean): void {
		onselectionchange(
			selected ? [...new Set([...selectedIds, id])] : selectedIds.filter((value) => value !== id)
		);
	}

	function reason(code: string): string {
		if (code === 'NO_CANDIDATE') return 'No external result';
		if (code === 'AMBIGUOUS') return 'Several equally likely releases';
		if (code === 'CONTRADICTORY') return 'Conflicting track evidence';
		return code.replaceAll('_', ' ').toLowerCase();
	}
</script>

{#if items.length === 0}
	<EmptyState
		icon={ClipboardCheck}
		title={state === 'keep_tagged'
			? 'No albums have been kept with local metadata yet.'
			: filtered
				? 'No review items match these filters.'
				: 'No albums need identification review.'}
		description={state === 'keep_tagged'
			? 'Albums you keep as tagged will appear here.'
			: filtered
				? 'Remove a filter or try a different search.'
				: 'Albums kept with local metadata remain playable and appear under their own filter.'}
	/>
{:else}
	<div
		class="hidden overflow-x-auto rounded-box border border-base-content/10 bg-base-100 lg:block"
	>
		<table class="table">
			<thead
				><tr
					><th><span class="sr-only">Select</span></th><th>Local album</th><th>Album artist</th><th
						>Root</th
					><th>Reason</th><th>Policy</th><th>Latest candidate</th><th>Updated</th><th
						><span class="sr-only">Action</span></th
					></tr
				></thead
			>
			<tbody>
				{#each items as item (item.id)}
					<tr>
						<td
							><input
								type="checkbox"
								class="checkbox checkbox-sm"
								checked={selectedIds.includes(item.id)}
								onchange={(event) => select(item.id, event.currentTarget.checked)}
								aria-label={`Select ${item.album_title}`}
							/></td
						>
						<td
							><div class="flex min-w-52 items-center gap-3">
								<AlbumImage
									mbid={item.local_album_id ?? item.release_group_mbid ?? item.id}
									alt=""
									size="xs"
									className="h-11 w-11 shrink-0"
								/>
								<div>
									<strong class="line-clamp-1">{item.album_title || 'Untitled local album'}</strong
									><span class="text-xs text-base-content/45">{item.track_count} tracks</span>
								</div>
							</div></td
						>
						<td>{item.album_artist_name || 'Unknown album artist'}</td><td
							><span class="text-xs">{rootLabels[item.root_id] ?? item.root_id}</span></td
						><td><span class="max-w-48 text-sm">{reason(item.reason_code)}</span></td><td
							><span class="badge badge-ghost badge-sm"
								>{item.effective_policy.replace('_', ' ')}</span
							></td
						><td>{item.candidate_count ? `${item.candidate_count} available` : 'None'}</td><td
							>{new Date(item.updated_at * 1000).toLocaleDateString()}</td
						><td
							><button class="btn btn-primary btn-sm" onclick={() => onreview(item.id)}
								>Review</button
							></td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<div class="space-y-3 lg:hidden">
		{#each items as item (item.id)}<LibraryReviewCard
				{item}
				selected={selectedIds.includes(item.id)}
				onselect={(value) => select(item.id, value)}
				onreview={() => onreview(item.id)}
			/>{/each}
	</div>
{/if}
