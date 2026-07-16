<script lang="ts">
	import { Filter, Search, X } from 'lucide-svelte';
	import type { LibraryReviewFilters as Filters } from '$lib/queries/library/LibraryReviewQueries.svelte';
	import type { LibraryPolicyTreeNode } from '$lib/queries/library/LibraryOperationsTypes';

	interface Props {
		filters: Filters;
		roots: LibraryPolicyTreeNode[];
		onchange: (filters: Filters) => void;
	}

	let { filters, roots, onchange }: Props = $props();
	let mobileDialog: HTMLDialogElement;
	let mobileHeading: HTMLHeadingElement;
	let mobileOpener: HTMLButtonElement | null = null;
	let search = $state('');
	let lastFilterSearch = $state<string | undefined>(undefined);

	$effect(() => {
		if (filters.search !== lastFilterSearch) {
			lastFilterSearch = filters.search;
			search = filters.search ?? '';
		}
	});

	function update(key: keyof Filters, value: string): void {
		onchange({ ...filters, cursor: undefined, [key]: value || undefined });
	}

	function submitSearch(event: SubmitEvent): void {
		event.preventDefault();
		update('search', search.trim());
	}

	function openMobileFilters(event: MouseEvent & { currentTarget: HTMLButtonElement }): void {
		mobileOpener = event.currentTarget;
		mobileDialog.showModal();
		mobileHeading.focus();
	}

	const chips = $derived(
		(
			[
				['state', filters.state],
				['reasonCode', filters.reasonCode],
				['rootId', filters.rootId],
				['policy', filters.policy]
			] as Array<[keyof Filters, string | undefined]>
		).filter((entry): entry is [keyof Filters, string] => Boolean(entry[1]))
	);
</script>

<div
	class="sticky top-16 z-20 space-y-2 rounded-box border border-base-content/10 bg-base-100/95 p-3 backdrop-blur"
>
	<div class="flex gap-2">
		<form class="join min-w-0 flex-1" onsubmit={submitSearch}>
			<label class="input input-bordered input-sm join-item flex min-w-0 flex-1 items-center gap-2"
				><Search class="h-4 w-4 text-base-content/45" /><input
					class="min-w-0 grow"
					bind:value={search}
					placeholder="Search local albums"
					aria-label="Search review items"
				/></label
			>
			<button class="btn btn-primary btn-sm join-item" type="submit">Search</button>
		</form>
		<button class="btn btn-outline btn-sm md:hidden" onclick={openMobileFilters}
			><Filter class="h-4 w-4" /> Filters</button
		>
	</div>
	<div class="hidden grid-cols-2 gap-2 md:grid lg:grid-cols-5">
		<select
			class="select select-bordered select-sm"
			value={filters.rootId ?? ''}
			aria-label="Library root"
			onchange={(event) => update('rootId', event.currentTarget.value)}
			><option value="">All library roots</option>{#each roots as root (root.id)}<option
					value={root.id}>{root.label}</option
				>{/each}</select
		>
		<select
			class="select select-bordered select-sm"
			value={filters.state ?? ''}
			aria-label="Review state"
			onchange={(event) => update('state', event.currentTarget.value)}
			><option value="">All states</option><option value="needs_review">Needs review</option><option
				value="keep_tagged">Keep as tagged</option
			><option value="excluded">Excluded</option></select
		>
		<select
			class="select select-bordered select-sm"
			value={filters.reasonCode ?? ''}
			aria-label="Review reason"
			onchange={(event) => update('reasonCode', event.currentTarget.value)}
			><option value="">All reasons</option><option value="NO_CANDIDATE">No external result</option
			><option value="AMBIGUOUS">Several equally likely releases</option><option
				value="CONTRADICTORY">Conflicting track evidence</option
			></select
		>
		<select
			class="select select-bordered select-sm"
			value={filters.policy ?? ''}
			aria-label="Identification policy"
			onchange={(event) => update('policy', event.currentTarget.value)}
			><option value="">All policies</option><option value="automatic"
				>Automatic identification</option
			><option value="local_metadata">Local metadata</option><option value="excluded"
				>Excluded</option
			></select
		>
		<select
			class="select select-bordered select-sm"
			value={filters.sort ?? 'newest'}
			aria-label="Review sort"
			onchange={(event) => update('sort', event.currentTarget.value)}
			><option value="newest">Recently updated</option><option value="oldest">Oldest first</option
			><option value="album">Album title</option><option value="artist">Album artist</option><option
				value="root">Library root</option
			></select
		>
	</div>
	{#if chips.length}
		<div class="flex flex-wrap gap-1.5" aria-label="Active review filters">
			{#each chips as [key, value] (key)}
				<button class="badge badge-outline gap-1" onclick={() => update(key, '')}
					>{value.replaceAll('_', ' ')}
					<X class="h-3 w-3" /><span class="sr-only">Remove filter</span></button
				>
			{/each}
		</div>
	{/if}
</div>

<dialog
	bind:this={mobileDialog}
	class="modal"
	aria-labelledby="mobile-review-filters-title"
	onclose={() => mobileOpener?.focus()}
>
	<div class="modal-box h-[min(100dvh,34rem)] max-w-md">
		<h2
			bind:this={mobileHeading}
			id="mobile-review-filters-title"
			tabindex="-1"
			class="text-lg font-bold"
		>
			Review filters
		</h2>
		<div class="mt-4 space-y-3">
			<label class="form-control"
				><span class="label-text">State</span><select
					class="select select-bordered"
					value={filters.state ?? ''}
					onchange={(event) => update('state', event.currentTarget.value)}
					><option value="">All states</option><option value="needs_review">Needs review</option
					><option value="keep_tagged">Keep as tagged</option><option value="excluded"
						>Excluded</option
					></select
				></label
			><label class="form-control"
				><span class="label-text">Reason</span><select
					class="select select-bordered"
					value={filters.reasonCode ?? ''}
					onchange={(event) => update('reasonCode', event.currentTarget.value)}
					><option value="">All reasons</option><option value="NO_CANDIDATE"
						>No external result</option
					><option value="AMBIGUOUS">Several equally likely releases</option><option
						value="CONTRADICTORY">Conflicting track evidence</option
					></select
				></label
			><label class="form-control"
				><span class="label-text">Library root</span><select
					class="select select-bordered"
					value={filters.rootId ?? ''}
					onchange={(event) => update('rootId', event.currentTarget.value)}
					><option value="">All library roots</option>{#each roots as root (root.id)}<option
							value={root.id}>{root.label}</option
						>{/each}</select
				></label
			><label class="form-control"
				><span class="label-text">Policy</span><select
					class="select select-bordered"
					value={filters.policy ?? ''}
					onchange={(event) => update('policy', event.currentTarget.value)}
					><option value="">All policies</option><option value="automatic"
						>Automatic identification</option
					><option value="local_metadata">Local metadata</option><option value="excluded"
						>Excluded</option
					></select
				></label
			><label class="form-control"
				><span class="label-text">Sort</span><select
					class="select select-bordered"
					value={filters.sort ?? 'newest'}
					onchange={(event) => update('sort', event.currentTarget.value)}
					><option value="newest">Recently updated</option><option value="oldest"
						>Oldest first</option
					><option value="album">Album title</option><option value="artist">Album artist</option
					><option value="root">Library root</option></select
				></label
			>
		</div>
		<div class="modal-action">
			<button class="btn btn-primary" onclick={() => mobileDialog.close()}>Done</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button aria-label="Close filters">close</button>
	</form>
</dialog>
