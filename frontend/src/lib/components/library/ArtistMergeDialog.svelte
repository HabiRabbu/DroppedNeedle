<script lang="ts">
	import { goto } from '$app/navigation';
	import { ChevronDown, UsersRound } from 'lucide-svelte';
	import type { LibraryArtistSummary } from '$lib/types';
	import {
		getLibraryArtistDetailQuery,
		getLibraryArtistsInfiniteQuery
	} from '$lib/queries/library/LibraryQueries.svelte';
	import {
		applyArtistMerge,
		previewArtistMerge
	} from '$lib/queries/library/LibraryCatalogMutations.svelte';
	import type { MembershipPreviewResponse } from '$lib/queries/library/LibraryOperationsTypes';

	interface Props {
		artist: LibraryArtistSummary;
	}
	let { artist }: Props = $props();
	let dialog: HTMLDialogElement;
	let dialogHeading: HTMLHeadingElement;
	let opener: HTMLButtonElement | null = null;
	let search = $state('');
	let duplicateId = $state<string | null>(null);
	let selectedDuplicate = $state<LibraryArtistSummary | null>(null);
	let survivingId = $state('');
	let providerChoice = $state<'detach' | 'retain_survivor'>('detach');
	let confirmed = $state(false);
	let stalePreview = $state(false);
	let previewResult = $state<MembershipPreviewResponse | null>(null);
	const artists = getLibraryArtistsInfiniteQuery(() => ({
		sortBy: 'name',
		sortOrder: 'asc',
		q: search
	}));
	const duplicate = getLibraryArtistDetailQuery(() => duplicateId ?? '');
	const duplicateArtist = $derived(duplicate.data ?? selectedDuplicate);
	const preview = previewArtistMerge();
	const apply = applyArtistMerge();

	function open(event: MouseEvent & { currentTarget: HTMLButtonElement }): void {
		opener = event.currentTarget;
		search = '';
		duplicateId = null;
		selectedDuplicate = null;
		survivingId = artist.id;
		confirmed = false;
		stalePreview = false;
		preview.reset();
		previewResult = null;
		dialog.showModal();
		dialogHeading.focus();
	}

	function request() {
		if (!duplicateArtist) return null;
		return {
			source_artist_ids: [artist.id, duplicateArtist.id],
			surviving_artist_id: survivingId,
			expected_revisions: {
				[artist.id]: artist.row_revision,
				[duplicateArtist.id]: duplicateArtist.row_revision
			}
		};
	}

	async function showPreview(): Promise<void> {
		const input = request();
		if (!input) return;
		confirmed = false;
		stalePreview = false;
		try {
			previewResult = await preview.mutateAsync(input);
		} catch {
			previewResult = null;
		}
	}

	async function merge(): Promise<void> {
		const input = request();
		if (!input || !previewResult || !confirmed) return;
		try {
			const result = await apply.mutateAsync({
				...input,
				preview_token: previewResult.preview_token,
				provider_choice: providerChoice
			});
			dialog.close();
			if (result.surviving_artist_id) await goto(`/artist/${result.surviving_artist_id}`);
		} catch {
			confirmed = false;
			stalePreview = true;
			preview.reset();
			previewResult = null;
		}
	}
</script>

<details class="dropdown dropdown-end">
	<summary class="btn btn-ghost btn-sm gap-2"
		><UsersRound class="h-4 w-4" /> Artist organization <ChevronDown class="h-3.5 w-3.5" /></summary
	>
	<ul class="menu dropdown-content z-30 mt-2 w-60 rounded-box bg-base-100 p-2 shadow-xl">
		<li><button onclick={open}>Merge duplicate artist...</button></li>
	</ul>
</details>

<dialog
	bind:this={dialog}
	class="modal"
	aria-labelledby="artist-merge-title"
	onclose={() => opener?.focus()}
>
	<div class="modal-box max-w-4xl">
		<h2 bind:this={dialogHeading} id="artist-merge-title" tabindex="-1" class="text-xl font-bold">
			Merge duplicate artist
		</h2>
		<p class="mt-1 text-sm text-base-content/60">
			Choose two local artists and the ID that should survive. Matching names or provider IDs do not
			merge artists automatically.
		</p>
		{#if stalePreview}
			<div class="alert alert-warning mt-4 text-sm">
				The artist records changed after this preview. Review the current details and preview the
				merge again.
			</div>
		{/if}
		{#if preview.isError}
			<div class="alert alert-error mt-4 text-sm">
				Could not preview this artist merge. Nothing has been changed.
			</div>
		{/if}

		<section class="mt-5" aria-labelledby="duplicate-artist-title">
			<h3 id="duplicate-artist-title" class="font-semibold">Find the duplicate</h3>
			<input
				class="input input-bordered mt-2 w-full"
				bind:value={search}
				placeholder="Search local artists"
			/>
			{#if search.trim().length >= 2}
				<div class="mt-2 max-h-52 overflow-auto rounded-box border border-base-content/10 p-2">
					{#each (artists.data?.pages.flatMap((group) => group.items) ?? []).filter((item) => item.id !== artist.id) as item (item.id)}
						<label class="flex cursor-pointer items-center gap-3 rounded-lg p-2 hover:bg-base-200">
							<input
								type="radio"
								name="duplicate-artist"
								class="radio radio-sm"
								checked={duplicateId === item.id}
								onchange={() => {
									duplicateId = item.id;
									selectedDuplicate = item;
									preview.reset();
									previewResult = null;
									confirmed = false;
								}}
							/>
							<span
								><strong>{item.name}</strong><span class="block text-xs text-base-content/55"
									>{item.album_count} albums · {item.track_count} tracks · {item.id}</span
								></span
							>
						</label>
					{/each}
				</div>
			{/if}
		</section>

		{#if duplicateArtist}
			<fieldset class="mt-5 rounded-box border border-base-content/10 p-4">
				<legend class="px-1 font-semibold">Choose the surviving local ID</legend>
				<label class="mt-2 flex items-start gap-3"
					><input
						type="radio"
						class="radio radio-sm mt-1"
						bind:group={survivingId}
						value={artist.id}
						onchange={() => {
							preview.reset();
							previewResult = null;
						}}
					/><span
						><strong>{artist.name}</strong><span
							class="block font-mono text-xs text-base-content/55">{artist.id}</span
						></span
					></label
				>
				<label class="mt-3 flex items-start gap-3"
					><input
						type="radio"
						class="radio radio-sm mt-1"
						bind:group={survivingId}
						value={duplicateArtist.id}
						onchange={() => {
							preview.reset();
							previewResult = null;
						}}
					/><span
						><strong>{duplicateArtist.name}</strong><span
							class="block font-mono text-xs text-base-content/55">{duplicateArtist.id}</span
						></span
					></label
				>
			</fieldset>
		{/if}

		{#if previewResult}
			<section
				class="mt-5 rounded-box bg-base-200/60 p-4"
				aria-labelledby="artist-merge-preview-title"
			>
				<h3 id="artist-merge-preview-title" class="font-semibold">Merge preview</h3>
				<p class="mt-1 text-sm">
					{previewResult.aliases.length} previous IDs will remain as aliases. Album and track IDs, files,
					and tags stay unchanged.
				</p>
				<dl class="mt-3 grid gap-2 text-sm sm:grid-cols-3">
					{#each Object.entries(previewResult.reference_counts) as [kind, count] (kind)}
						<div>
							<dt class="text-base-content/55">{kind.replaceAll('_', ' ')}</dt>
							<dd class="font-semibold">{count}</dd>
						</div>
					{/each}
				</dl>
				{#if previewResult.identity_conflicts.length}
					<div class="alert alert-warning mt-3 text-sm">
						<div class="w-full">
							<p>These artists have conflicting provider identities.</p>
							<label class="mt-2 flex items-center gap-2"
								><input
									type="radio"
									class="radio radio-sm"
									bind:group={providerChoice}
									value="detach"
								/> Detach provider identities</label
							><label class="mt-2 flex items-center gap-2"
								><input
									type="radio"
									class="radio radio-sm"
									bind:group={providerChoice}
									value="retain_survivor"
								/> Keep the survivor's provider identity</label
							>
						</div>
					</div>
				{/if}
				<label class="mt-4 flex items-start gap-2 text-sm"
					><input
						type="checkbox"
						class="checkbox checkbox-sm mt-0.5"
						bind:checked={confirmed}
					/><span>Merge these artists and preserve the retired IDs as aliases.</span></label
				>
			</section>
		{/if}

		<div class="modal-action">
			<form method="dialog"><button class="btn btn-ghost">Cancel</button></form>
			{#if previewResult}<button
					class="btn btn-primary"
					disabled={!confirmed || apply.isPending}
					onclick={() => void merge()}>Merge artists</button
				>{:else}<button
					class="btn btn-primary"
					disabled={!duplicateArtist || preview.isPending}
					onclick={() => void showPreview()}>Preview merge</button
				>{/if}
		</div>
	</div>
	<form method="dialog" class="modal-backdrop"><button>close</button></form>
</dialog>
