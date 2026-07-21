<script lang="ts">
	import { ExternalLink, LoaderCircle, RefreshCw, Search, Unlink } from 'lucide-svelte';
	import type { LibraryContribution } from '$lib/types';
	import {
		removeDiscogsReleaseMutation,
		searchDiscogsReleasesMutation,
		selectDiscogsReleaseMutation
	} from '$lib/queries/libraryContributions/LibraryContributionMutations.svelte';

	interface Props {
		contribution: LibraryContribution;
		canMutate: boolean;
	}

	let { contribution, canMutate }: Props = $props();
	let query = $state('');
	const searchMutation = searchDiscogsReleasesMutation();
	const selectMutation = selectDiscogsReleaseMutation();
	const removeMutation = removeDiscogsReleaseMutation();
	const selectedReference = $derived(
		contribution.source_selection.sources.find(
			(source) => source.provider === 'discogs' && source.entity_type === 'release'
		)
	);
	const selected = $derived(contribution.discogs_source?.release ?? null);
	const exactInput = $derived(/^\d+$/.test(query.trim()) || query.includes('discogs.com/release/'));

	function search(): void {
		if (!canMutate || searchMutation.isPending) return;
		const value = query.trim();
		if (
			/^\d+$/.test(value) ||
			/^https:\/\/(?:www\.)?discogs\.com\/release\/[1-9]\d*(?:-[^/?#]+)?\/?$/i.test(value)
		) {
			select(value);
			return;
		}
		searchMutation.mutate({ contributionId: contribution.id, query });
	}

	function select(releaseIdOrUrl: string): void {
		if (!canMutate || selectMutation.isPending) return;
		selectMutation.mutate({
			contributionId: contribution.id,
			expectedRowRevision: contribution.row_revision,
			releaseIdOrUrl
		});
	}
</script>

<section
	class="rounded-box border border-base-content/10 bg-base-100"
	aria-labelledby="discogs-title"
>
	<div class="border-b border-base-content/10 px-5 py-4 sm:px-6">
		<p class="text-xs font-bold uppercase tracking-[0.16em] text-base-content/40">
			Optional source
		</p>
		<h2 id="discogs-title" class="mt-1 text-lg font-bold">Find the exact Discogs release</h2>
		<p class="mt-1 text-sm text-base-content/55">
			Use a release URL or ID, or search by artist, title, barcode, label, or catalogue number.
		</p>
	</div>

	{#if selectedReference}
		<div class="p-5 sm:p-6">
			{#if contribution.discogs_source?.expired}
				<div class="alert alert-warning mb-4" role="status">
					<span
						>Discogs data is more than six hours old. Refresh it before comparing or submitting.</span
					>
				</div>
			{/if}
			<div class="flex flex-wrap items-start justify-between gap-4 rounded-box bg-base-200/55 p-4">
				<div class="min-w-0">
					<span class="badge badge-outline badge-sm"
						>Discogs release #{selectedReference.external_id}</span
					>
					<h3 class="mt-2 font-bold">{selected?.title ?? 'Selected release'}</h3>
					<p class="text-sm text-base-content/60">
						{selected?.artist_name ?? 'Refresh to display current Discogs metadata'}
						{#if selected?.country}
							· {selected.country}{/if}
						{#if selected?.released_date}
							· {selected.released_date}{/if}
					</p>
					<a
						class="link link-primary mt-2 inline-flex items-center gap-1 text-xs"
						href={selectedReference.canonical_url}
						target="_blank"
						rel="noopener noreferrer"
					>
						Data provided by Discogs <ExternalLink class="h-3 w-3" />
					</a>
				</div>
				<div class="flex gap-2">
					{#if canMutate}
						<button
							class="btn btn-ghost btn-sm gap-2"
							disabled={selectMutation.isPending}
							onclick={() => select(selectedReference.external_id)}
						>
							{#if selectMutation.isPending}<LoaderCircle
									class="h-4 w-4 animate-spin"
								/>{:else}<RefreshCw class="h-4 w-4" />{/if}
							Refresh
						</button>
						<button
							class="btn btn-ghost btn-sm gap-2 text-error"
							disabled={removeMutation.isPending}
							onclick={() =>
								removeMutation.mutate({
									contributionId: contribution.id,
									expectedRowRevision: contribution.row_revision
								})}
						>
							<Unlink class="h-4 w-4" /> Remove
						</button>
					{/if}
				</div>
			</div>
		</div>
	{:else}
		<form
			class="p-5 sm:p-6"
			onsubmit={(event) => {
				event.preventDefault();
				search();
			}}
		>
			<label class="form-control">
				<span class="label"><span class="label-text font-semibold">Discogs release</span></span>
				<div class="join w-full">
					<input
						class="input input-bordered join-item min-w-0 flex-1"
						bind:value={query}
						placeholder="Artist, title, barcode, release URL, or ID"
						disabled={!canMutate}
					/>
					<button
						class="btn btn-primary join-item gap-2"
						disabled={!canMutate || searchMutation.isPending || selectMutation.isPending}
					>
						{#if searchMutation.isPending}<LoaderCircle
								class="h-4 w-4 animate-spin"
							/>{:else}<Search class="h-4 w-4" />{/if}
						{exactInput ? 'Use release' : 'Search'}
					</button>
				</div>
			</label>

			{#if searchMutation.data}
				<div class="mt-5" aria-live="polite">
					{#if searchMutation.data.results.length === 0}
						<p class="rounded-box bg-base-200/55 p-4 text-sm text-base-content/60">
							No matching Discogs releases. Try an exact release URL or a broader search.
						</p>
					{:else}
						<ul class="space-y-2">
							{#each searchMutation.data.results as result (result.release_id)}
								<li class="rounded-box border border-base-content/10 bg-base-200/35 p-4">
									<div class="flex flex-wrap items-start justify-between gap-3">
										<div class="min-w-0">
											<h3 class="font-bold">{result.title}</h3>
											<p class="text-sm text-base-content/60">
												{result.artist_name || 'Artist not listed'}
												{#if result.year}
													· {result.year}{/if}
												{#if result.country}
													· {result.country}{/if}
											</p>
											<p class="mt-1 text-xs text-base-content/45">
												{result.label ?? 'Label not listed'}
												{#if result.catalogue_number}
													· {result.catalogue_number}{/if}
												{#if result.format_summary}
													· {result.format_summary}{/if}
											</p>
											<a
												class="link link-primary mt-2 inline-flex items-center gap-1 text-xs"
												href={result.canonical_url}
												target="_blank"
												rel="noopener noreferrer"
											>
												Data provided by Discogs <ExternalLink class="h-3 w-3" />
											</a>
										</div>
										<button
											type="button"
											class="btn btn-outline btn-sm"
											disabled={!canMutate || selectMutation.isPending}
											onclick={() => select(result.release_id)}>Select release</button
										>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}
		</form>
	{/if}
</section>
