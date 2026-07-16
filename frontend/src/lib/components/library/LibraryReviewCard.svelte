<script lang="ts">
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import type { ReviewListItem } from '$lib/queries/library/LibraryOperationsTypes';

	interface Props {
		item: ReviewListItem;
		selected: boolean;
		onselect: (selected: boolean) => void;
		onreview: () => void;
	}
	let { item, selected, onselect, onreview }: Props = $props();

	const reason = $derived(
		item.reason_code === 'NO_CANDIDATE'
			? 'No external result'
			: item.reason_code === 'AMBIGUOUS'
				? 'Several equally likely releases'
				: item.reason_code === 'CONTRADICTORY'
					? 'Conflicting track evidence'
					: item.reason_code.replaceAll('_', ' ').toLowerCase()
	);
</script>

<article class="rounded-box border border-base-content/10 bg-base-100 p-3">
	<div class="flex gap-3">
		<AlbumImage
			mbid={item.local_album_id ?? item.release_group_mbid ?? item.id}
			alt={`Cover for ${item.album_title}`}
			size="sm"
			className="h-16 w-16 shrink-0"
		/>
		<div class="min-w-0 flex-1">
			<h3 class="truncate font-semibold">{item.album_title || 'Untitled local album'}</h3>
			<p class="truncate text-sm text-base-content/60">
				{item.album_artist_name || 'Unknown album artist'}
			</p>
			<p class="mt-1 text-xs text-warning">{reason}</p>
		</div>
		<span class="badge badge-ghost badge-sm">{item.state.replaceAll('_', ' ')}</span>
	</div>
	<div class="mt-3 flex items-center justify-between gap-2">
		<label class="flex items-center gap-2 text-sm"
			><input
				type="checkbox"
				class="checkbox checkbox-sm"
				checked={selected}
				onchange={(event) => onselect(event.currentTarget.checked)}
			/> Select</label
		><button class="btn btn-primary btn-sm" onclick={onreview}>Review</button>
	</div>
</article>
