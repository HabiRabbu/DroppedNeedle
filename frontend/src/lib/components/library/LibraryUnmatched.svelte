<script lang="ts">
	import { CheckCircle, FolderOpen, ChevronRight } from 'lucide-svelte';
	import { getLibraryUnmatchedQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import UnmatchedMatcher from './UnmatchedMatcher.svelte';
	import { groupUnmatched, type UnmatchedGroup } from './unmatchedGrouping';

	const unmatchedQuery = getLibraryUnmatchedQuery();
	const groups = $derived(groupUnmatched(unmatchedQuery.data?.items ?? []));
	const totalFiles = $derived(unmatchedQuery.data?.items.length ?? 0);

	let active = $state<UnmatchedGroup | null>(null);

	function preview(group: UnmatchedGroup): string {
		const names = group.files
			.slice(0, 4)
			.map((f) => f.extracted_title || (f.file_path.split('/').pop() ?? ''));
		const more = group.files.length - names.length;
		return names.join(' · ') + (more > 0 ? ` · +${more} more` : '');
	}
</script>

{#if unmatchedQuery.isLoading}
	<div class="grid gap-3 sm:grid-cols-2">
		{#each Array(4) as _, i (i)}
			<div class="skeleton h-32 w-full rounded-box"></div>
		{/each}
	</div>
{:else if unmatchedQuery.isError}
	<div class="alert alert-error">
		Failed to load unmatched files: {unmatchedQuery.error.message}
	</div>
{:else if groups.length === 0}
	<EmptyState
		icon={CheckCircle}
		title="No files need review"
		description="Everything from your last scan matched cleanly."
	/>
{:else}
	<div class="mb-3 text-sm text-base-content/55">
		{totalFiles} file{totalFiles === 1 ? '' : 's'} across {groups.length} folder{groups.length === 1
			? ''
			: 's'} need attributing.
	</div>
	<div class="grid gap-3 sm:grid-cols-2">
		{#each groups as group (group.folder)}
			<button
				class="group flex items-start gap-3 rounded-box border border-base-300 bg-base-200 p-4 text-left transition-colors hover:border-primary/40 hover:bg-base-300/60"
				onclick={() => (active = group)}
			>
				<div
					class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"
				>
					<FolderOpen class="h-5 w-5" />
				</div>
				<div class="min-w-0 flex-1">
					<div class="flex items-center justify-between gap-2">
						<h3 class="truncate font-semibold">{group.guessedAlbum || group.folderName}</h3>
						<span class="badge badge-primary badge-sm shrink-0">{group.files.length}</span>
					</div>
					<p class="truncate text-sm text-base-content/55">
						{group.guessedArtist || 'Unknown artist'}
					</p>
					<p class="mt-0.5 truncate font-mono text-xs text-base-content/35" title={group.folder}>
						{group.folder}
					</p>
					<p class="mt-1.5 line-clamp-2 text-xs text-base-content/45">{preview(group)}</p>
				</div>
				<ChevronRight
					class="mt-1 h-5 w-5 shrink-0 text-base-content/30 transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
				/>
			</button>
		{/each}
	</div>
{/if}

{#if active}
	<UnmatchedMatcher group={active} onclose={() => (active = null)} />
{/if}
