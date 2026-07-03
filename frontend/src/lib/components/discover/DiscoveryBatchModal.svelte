<script lang="ts">
	import { Check, Download, Loader2, X } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import AlbumImage from '$lib/components/AlbumImage.svelte';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { createDiscoveryBatch } from '$lib/queries/discover/DiscoveryBatchQuery.svelte';
	import type { HomeAlbum } from '$lib/types';

	interface Props {
		open: boolean;
		sectionTitle: string;
		sectionKey: string;
		albums: HomeAlbum[];
	}

	let { open = $bindable(false), sectionTitle, sectionKey, albums }: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let name = $state('');
	let deselected = new SvelteSet<string>();
	let submitting = $state(false);

	// dedupe by mbid: a repeated album is meaningless here and a duplicate key
	// would crash the keyed {#each} below (and the batch it creates)
	const eligible = $derived(
		albums.filter((a, i) => a.mbid && albums.findIndex((b) => b.mbid === a.mbid) === i)
	);
	const selectedCount = $derived(
		eligible.filter((a) => !a.in_library && !deselected.has(a.mbid!)).length
	);
	const needsApproval = $derived(authStore.user?.role === 'user');

	$effect(() => {
		if (!dialogEl) return;
		if (open) {
			name = `${sectionTitle} — ${new Date().toLocaleDateString(undefined, {
				month: 'short',
				day: 'numeric'
			})}`;
			deselected.clear();
			// in-library albums start unchecked: requesting them is a no-op
			for (const a of eligible.filter((x) => x.in_library)) deselected.add(a.mbid!);
			dialogEl.showModal();
		} else if (dialogEl.open) {
			dialogEl.close();
		}
	});

	function toggle(mbid: string) {
		if (deselected.has(mbid)) {
			deselected.delete(mbid);
		} else {
			deselected.add(mbid);
		}
	}

	async function submit() {
		if (submitting || selectedCount === 0) return;
		submitting = true;
		try {
			const items = eligible
				.filter((a) => !deselected.has(a.mbid!))
				.map((a) => ({
					release_group_mbid: a.mbid!,
					artist_mbid: a.artist_mbid ?? '',
					album_name: a.name,
					artist_name: a.artist_name ?? ''
				}));
			const created = await createDiscoveryBatch({
				name: name.trim() || sectionTitle,
				source_section: sectionKey,
				items
			});
			if (created) open = false;
		} finally {
			submitting = false;
		}
	}
</script>

<dialog bind:this={dialogEl} class="modal" onclose={() => (open = false)}>
	<div class="modal-box max-w-xl">
		<div class="mb-1 flex items-start justify-between gap-3">
			<h3 class="text-lg font-bold">Download this section</h3>
			<button class="btn btn-circle btn-ghost btn-sm" onclick={() => (open = false)}>
				<X class="h-4 w-4" />
			</button>
		</div>
		<p class="mb-4 text-sm text-base-content/60">
			Files a request for each selected album - the same rules as requesting them one by one.
			{#if needsApproval}These will wait for admin approval.{/if}
			You can remove the whole batch later from the Downloads page.
		</p>

		<label class="form-control mb-4 w-full">
			<span
				class="label-text mb-1 text-xs font-semibold uppercase tracking-wide text-base-content/50"
			>
				Batch name
			</span>
			<input type="text" class="input input-bordered input-sm w-full" bind:value={name} />
		</label>

		<div class="max-h-80 space-y-1 overflow-y-auto pr-1">
			{#each eligible as album (album.mbid)}
				<label
					class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-base-content/5 {album.in_library
						? 'opacity-60'
						: ''}"
				>
					<input
						type="checkbox"
						class="checkbox checkbox-primary checkbox-sm"
						checked={!deselected.has(album.mbid!)}
						onchange={() => toggle(album.mbid!)}
					/>
					<AlbumImage
						mbid={album.mbid!}
						alt={album.name}
						size="full"
						lazy={true}
						rounded="md"
						className="block h-10 w-10 shrink-0 object-cover"
						customUrl={album.image_url || null}
					/>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium">{album.name}</p>
						<p class="truncate text-xs text-base-content/50">{album.artist_name}</p>
					</div>
					{#if album.in_library}
						<span class="badge badge-success badge-sm gap-1 shrink-0">
							<Check class="h-3 w-3" /> Owned
						</span>
					{/if}
				</label>
			{/each}
		</div>

		<div class="modal-action">
			<button class="btn btn-ghost btn-sm" onclick={() => (open = false)}>Cancel</button>
			<button
				class="btn btn-primary btn-sm gap-2"
				disabled={submitting || selectedCount === 0}
				onclick={submit}
			>
				{#if submitting}
					<Loader2 class="h-4 w-4 animate-spin" />
				{:else}
					<Download class="h-4 w-4" />
				{/if}
				Request {selectedCount} album{selectedCount === 1 ? '' : 's'}
			</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
