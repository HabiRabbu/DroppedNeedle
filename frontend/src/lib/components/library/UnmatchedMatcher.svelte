<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { Search, X, Check, Music, GripVertical, TriangleAlert, Trash2 } from 'lucide-svelte';
	import {
		getAlbumSearchQuery,
		getAlbumTracksQuery
	} from '$lib/queries/library/LibraryQueries.svelte';
	import {
		resolveUnmatchedBatch,
		resolveUnmatchedFile
	} from '$lib/queries/library/LibraryMutations.svelte';
	import { getCoverUrl } from '$lib/utils/errorHandling';
	import { toastStore } from '$lib/stores/toast';
	import type { Album, ManualReviewEntry, Track } from '$lib/types';
	import type { UnmatchedGroup } from './unmatchedGrouping';
	import { suggestAssignments } from './unmatchedMatching';

	interface Props {
		group: UnmatchedGroup;
		onclose: () => void;
	}
	let { group, onclose }: Props = $props();

	let searchTerm = $state(
		untrack(() => [group.guessedArtist, group.guessedAlbum].filter(Boolean).join(' ').trim())
	);
	let selectedAlbum = $state<Album | null>(null);
	let assigned = $state<Record<number, number>>({});
	let suggestedFor = $state<string | null>(null);
	let dragOverSlot = $state<number | null>(null);
	let poolDragOver = $state(false);

	const searchQuery = getAlbumSearchQuery(() => searchTerm);
	const tracksQuery = getAlbumTracksQuery(() => selectedAlbum?.musicbrainz_id ?? null);
	const batch = resolveUnmatchedBatch();
	const reject = resolveUnmatchedFile();

	const results = $derived(searchQuery.data ?? []);
	const tracks = $derived<Track[]>(tracksQuery.data?.tracks ?? []);
	const poolFiles = $derived(group.files.filter((f) => assigned[f.id] === undefined));
	const assignedCount = $derived(Object.keys(assigned).length);

	function fileForSlot(i: number): ManualReviewEntry | undefined {
		return group.files.find((f) => assigned[f.id] === i);
	}

	$effect(() => {
		const mbid = selectedAlbum?.musicbrainz_id;
		if (mbid && tracks.length && mbid !== untrack(() => suggestedFor)) {
			untrack(() => {
				assigned = suggestAssignments(group.files, tracks);
				suggestedFor = mbid;
			});
		}
	});

	function assignToSlot(fileId: number, slot: number) {
		const next = { ...assigned };
		for (const [id, s] of Object.entries(next)) if (s === slot) delete next[Number(id)];
		next[fileId] = slot;
		assigned = next;
	}
	function unassign(fileId: number) {
		const { [fileId]: _drop, ...rest } = assigned;
		assigned = rest;
	}

	function selectAlbum(album: Album) {
		selectedAlbum = album;
		assigned = {};
		suggestedFor = null;
	}
	function changeAlbum() {
		selectedAlbum = null;
		assigned = {};
	}

	function onSlotDrop(e: DragEvent, slot: number) {
		e.preventDefault();
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (id) assignToSlot(id, slot);
		dragOverSlot = null;
	}
	function onPoolDrop(e: DragEvent) {
		e.preventDefault();
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (id) unassign(id);
		poolDragOver = false;
	}

	function durationDelta(file: ManualReviewEntry | undefined, track: Track): number | null {
		if (!file?.duration || !track.length) return null;
		return Math.abs(file.duration - track.length / 1000) / (track.length / 1000);
	}

	function fmtDur(seconds: number | null | undefined): string {
		if (!seconds && seconds !== 0) return '—';
		const s = Math.round(seconds);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	async function confirm() {
		if (!selectedAlbum || assignedCount === 0) return;
		const items = Object.entries(assigned).map(([fileId, slot]) => ({
			review_id: Number(fileId),
			recording_mbid: tracks[slot]?.recording_id ?? null
		}));
		try {
			const res = await batch.mutateAsync({
				release_group_mbid: selectedAlbum.musicbrainz_id,
				items
			});
			if (res.failed.length) {
				toastStore.show({
					message: `Imported ${res.resolved}, ${res.failed.length} failed`,
					type: 'info'
				});
			} else {
				toastStore.show({ message: `Imported ${res.resolved} file(s)`, type: 'success' });
			}
			onclose();
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to import files',
				type: 'error'
			});
		}
	}

	async function rejectFile(fileId: number) {
		try {
			await reject.mutateAsync({ id: fileId, resolution: 'reject' });
			unassign(fileId);
		} catch {
			toastStore.show({ message: 'Failed to reject file', type: 'error' });
		}
	}

	onMount(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') onclose();
		};
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	});
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 z-100 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center"
	onclick={(e) => {
		if (e.target === e.currentTarget) onclose();
	}}
>
	<div
		class="matcher-panel flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-t-2xl border border-base-300 bg-base-100 shadow-2xl sm:rounded-2xl"
	>
		<div class="flex items-center justify-between gap-3 border-b border-base-300 p-4">
			<div class="min-w-0">
				<h2 class="truncate text-lg font-bold">Match folder</h2>
				<p class="truncate font-mono text-xs text-base-content/45" title={group.folder}>
					{group.folder}
				</p>
			</div>
			<button class="btn btn-ghost btn-sm btn-circle" onclick={onclose} aria-label="Close">
				<X class="h-5 w-5" />
			</button>
		</div>

		<div class="border-b border-base-300 p-4">
			{#if !selectedAlbum}
				<label class="input input-bordered flex items-center gap-2">
					<Search class="h-4 w-4 opacity-50" />
					<input
						type="text"
						class="grow"
						placeholder="Search for the album…"
						bind:value={searchTerm}
						aria-label="Search for an album"
					/>
					{#if searchQuery.isFetching}<span class="loading loading-spinner loading-xs"></span>{/if}
				</label>
				{#if results.length}
					<div class="mt-2 max-h-56 space-y-1 overflow-y-auto">
						{#each results as album (album.musicbrainz_id)}
							<button
								class="flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors hover:bg-base-200"
								onclick={() => selectAlbum(album)}
							>
								<img
									src={getCoverUrl(album.cover_url, album.musicbrainz_id)}
									alt=""
									class="h-10 w-10 shrink-0 rounded bg-base-300 object-cover"
									loading="lazy"
								/>
								<div class="min-w-0">
									<p class="truncate text-sm font-medium">{album.title}</p>
									<p class="truncate text-xs text-base-content/55">
										{album.artist || 'Unknown artist'}{album.year ? ` · ${album.year}` : ''}
									</p>
								</div>
							</button>
						{/each}
					</div>
				{:else if searchTerm.trim().length >= 2 && !searchQuery.isFetching}
					<p class="mt-2 text-sm text-base-content/50">No albums found — try a different search.</p>
				{/if}
			{:else}
				<div class="flex items-center gap-3">
					<img
						src={getCoverUrl(selectedAlbum.cover_url, selectedAlbum.musicbrainz_id)}
						alt=""
						class="h-12 w-12 shrink-0 rounded bg-base-300 object-cover"
					/>
					<div class="min-w-0 flex-1">
						<p class="truncate font-semibold">{selectedAlbum.title}</p>
						<p class="truncate text-sm text-base-content/55">
							{selectedAlbum.artist || 'Unknown artist'}{selectedAlbum.year
								? ` · ${selectedAlbum.year}`
								: ''} · {tracks.length} tracks
						</p>
					</div>
					<button class="btn btn-ghost btn-xs" onclick={changeAlbum}>Change</button>
				</div>
			{/if}
		</div>

		{#if selectedAlbum}
			<div
				class="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-hidden bg-base-300 md:grid-cols-2"
			>
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="flex min-h-0 flex-col bg-base-100"
					class:bg-base-200={poolDragOver}
					ondragover={(e) => {
						e.preventDefault();
						poolDragOver = true;
					}}
					ondragleave={() => (poolDragOver = false)}
					ondrop={onPoolDrop}
				>
					<div
						class="flex items-center justify-between px-4 py-2 text-xs font-semibold text-base-content/60"
					>
						<span>YOUR FILES</span>
						<span>{poolFiles.length} unplaced</span>
					</div>
					<div class="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
						{#each poolFiles as file (file.id)}
							<div
								class="group flex items-center gap-2 rounded-lg border border-base-300 bg-base-200 p-2"
								draggable="true"
								ondragstart={(e) => e.dataTransfer?.setData('text/plain', String(file.id))}
								role="listitem"
							>
								<GripVertical class="h-4 w-4 shrink-0 cursor-grab text-base-content/30" />
								<div class="min-w-0 flex-1">
									<p class="truncate text-sm">
										{#if file.track_number}<span class="text-base-content/40"
												>{file.track_number}.</span
											>
										{/if}{file.extracted_title || file.file_path.split('/').pop()}
									</p>
									<p class="text-xs text-base-content/45">
										{fmtDur(file.duration)}{file.file_format
											? ` · ${file.file_format.toUpperCase()}`
											: ''}
									</p>
								</div>
								<button
									class="btn btn-ghost btn-xs btn-circle opacity-0 transition-opacity group-hover:opacity-60 hover:!opacity-100"
									title="Reject (not music we want)"
									aria-label="Reject file"
									onclick={() => rejectFile(file.id)}
								>
									<Trash2 class="h-3.5 w-3.5" />
								</button>
							</div>
						{/each}
						{#if poolFiles.length === 0}
							<p class="px-1 py-6 text-center text-sm text-base-content/40">
								All files placed — ready to confirm.
							</p>
						{/if}
					</div>
				</div>

				<div class="flex min-h-0 flex-col bg-base-100">
					<div class="px-4 py-2 text-xs font-semibold text-base-content/60">TRACKLIST</div>
					<div class="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3">
						{#if tracksQuery.isLoading}
							{#each Array(6) as _, i (i)}
								<div class="skeleton h-11 w-full rounded-lg"></div>
							{/each}
						{:else}
							{#each tracks as track, i (i)}
								{@const placed = fileForSlot(i)}
								{@const delta = durationDelta(placed, track)}
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div
									class="flex items-center gap-2 rounded-lg border p-2 transition-colors"
									class:border-base-300={dragOverSlot !== i && !placed}
									class:border-primary={dragOverSlot === i}
									class:bg-primary={dragOverSlot === i}
									class:bg-opacity-10={dragOverSlot === i}
									class:border-accent={!!placed && dragOverSlot !== i}
									class:bg-base-200={!!placed && dragOverSlot !== i}
									ondragover={(e) => {
										e.preventDefault();
										dragOverSlot = i;
									}}
									ondragleave={() => (dragOverSlot = null)}
									ondrop={(e) => onSlotDrop(e, i)}
								>
									<span class="w-6 shrink-0 text-center text-xs text-base-content/40">
										{track.position}
									</span>
									{#if placed}
										<div
											class="flex min-w-0 flex-1 items-center gap-2"
											draggable="true"
											ondragstart={(e) => e.dataTransfer?.setData('text/plain', String(placed.id))}
											role="listitem"
										>
											<Music class="h-4 w-4 shrink-0 text-accent" />
											<div class="min-w-0 flex-1">
												<p class="truncate text-sm">{track.title}</p>
												<p class="truncate text-xs text-base-content/45">
													← {placed.extracted_title || placed.file_path.split('/').pop()}
												</p>
											</div>
											{#if delta !== null}
												{#if delta <= 0.15}
													<span class="tooltip" data-tip="Duration matches">
														<Check class="h-4 w-4 text-success" />
													</span>
												{:else}
													<span class="tooltip" data-tip="Duration looks off — wrong track?">
														<TriangleAlert class="h-4 w-4 text-warning" />
													</span>
												{/if}
											{/if}
											<button
												class="btn btn-ghost btn-xs btn-circle"
												aria-label="Unplace file"
												onclick={() => unassign(placed.id)}
											>
												<X class="h-3.5 w-3.5" />
											</button>
										</div>
									{:else}
										<div class="min-w-0 flex-1">
											<p class="truncate text-sm text-base-content/70">{track.title}</p>
										</div>
										<span class="shrink-0 text-xs text-base-content/35"
											>{fmtDur(track.length ? track.length / 1000 : null)}</span
										>
									{/if}
								</div>
							{/each}
						{/if}
					</div>
				</div>
			</div>

			<div class="flex items-center justify-between gap-3 border-t border-base-300 p-4">
				<span class="text-sm text-base-content/55">
					{assignedCount} of {group.files.length} placed
				</span>
				<div class="flex gap-2">
					<button class="btn btn-ghost btn-sm" onclick={onclose}>Cancel</button>
					<button
						class="btn btn-primary btn-sm"
						disabled={assignedCount === 0 || batch.isPending}
						onclick={confirm}
					>
						{#if batch.isPending}<span class="loading loading-spinner loading-xs"></span>{/if}
						Confirm {assignedCount} match{assignedCount === 1 ? '' : 'es'}
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>

<style>
	.matcher-panel {
		animation: matcher-in 0.25s cubic-bezier(0.16, 1, 0.3, 1);
	}
	@keyframes matcher-in {
		from {
			opacity: 0;
			transform: translateY(12px) scale(0.99);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.matcher-panel {
			animation: none;
		}
	}
</style>
