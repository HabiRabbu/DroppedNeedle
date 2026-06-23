<script lang="ts">
	import { cancelDownload } from '$lib/queries/downloads/DownloadMutations.svelte';
	import {
		getSearchJobQuery,
		pickSearchCandidate
	} from '$lib/queries/downloads/SearchQueries.svelte';
	import type { DownloadTask } from '$lib/types';

	import SearchResultCard from './SearchResultCard.svelte';

	let { task }: { task: DownloadTask } = $props();

	const jobQuery = getSearchJobQuery(() => task.search_job_id ?? '');
	const pick = pickSearchCandidate();
	const cancel = cancelDownload();

	let showAll = $state(false);
	let pickingIndex = $state<number | null>(null);

	const candidates = $derived(jobQuery.data?.candidates ?? []);
	// visible is a prefix of candidates, so each item's index matches the full-array candidate_index the backend expects
	const visible = $derived(showAll ? candidates : candidates.slice(0, 3));

	function handlePick(index: number) {
		if (!task.search_job_id) return;
		pickingIndex = index;
		pick.mutate(
			{ jobId: task.search_job_id, candidate_index: index },
			{ onSettled: () => (pickingIndex = null) }
		);
	}
</script>

<div class="mt-3 space-y-3 border-t border-base-content/10 pt-3">
	{#if jobQuery.isLoading}
		<div class="skeleton h-20 w-full rounded-box"></div>
	{:else if candidates.length === 0}
		<p class="text-sm text-base-content/60">No candidates available to review.</p>
	{:else}
		{#each visible as candidate, i (candidate.username + candidate.parent_directory)}
			<SearchResultCard {candidate} picking={pickingIndex === i} onPick={() => handlePick(i)} />
		{/each}
		<div class="flex items-center justify-between gap-2">
			{#if candidates.length > 3}
				<button class="btn btn-ghost btn-xs" onclick={() => (showAll = !showAll)}>
					{showAll ? 'Show fewer' : `Show all ${candidates.length} candidates`}
				</button>
			{:else}
				<span></span>
			{/if}
			<button
				class="btn btn-ghost btn-xs text-error"
				onclick={() => cancel.mutate(task.id)}
				disabled={cancel.isPending}
			>
				Cancel request
			</button>
		</div>
	{/if}
</div>
