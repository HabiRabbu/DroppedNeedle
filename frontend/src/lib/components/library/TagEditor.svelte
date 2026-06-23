<script lang="ts">
	import { api } from '$lib/api/client';
	import { API } from '$lib/constants';
	import { updateTrackTags } from '$lib/queries/library/LibraryMutations.svelte';
	import { toastStore } from '$lib/stores/toast';
	import type { LibraryTrack, TrackTagUpdate } from '$lib/types';

	interface Props {
		track: LibraryTrack;
		releaseGroupMbid: string;
		open: boolean;
		onClose?: () => void;
	}

	let { track, releaseGroupMbid, open = $bindable(false), onClose }: Props = $props();

	const save = updateTrackTags();

	const EMPTY: TrackTagUpdate = {
		title: '',
		artist: '',
		album: '',
		track_number: 0,
		album_artist: null,
		disc_number: 1,
		year: null,
		genre: null,
		musicbrainz_release_group_id: null,
		musicbrainz_release_id: null,
		musicbrainz_recording_id: null,
		musicbrainz_artist_id: null,
		musicbrainz_album_artist_id: null
	};

	const MBID_FIELDS = [
		'musicbrainz_release_group_id',
		'musicbrainz_release_id',
		'musicbrainz_recording_id',
		'musicbrainz_artist_id',
		'musicbrainz_album_artist_id'
	] as const;

	let form = $state<TrackTagUpdate>({ ...EMPTY });
	let original = $state<TrackTagUpdate>({ ...EMPTY });
	let loading = $state(false);
	let loadError = $state<string | null>(null);
	let confirmMbid = $state(false);
	let dialogEl = $state<HTMLDialogElement | null>(null);

	$effect(() => {
		if (open) {
			dialogEl?.showModal();
			void load();
		} else {
			dialogEl?.close();
		}
	});

	async function load() {
		loading = true;
		loadError = null;
		confirmMbid = false;
		try {
			const tags = await api.global.get<TrackTagUpdate>(API.library.trackTags(track.id));
			form = { ...EMPTY, ...tags };
			original = { ...form };
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Failed to load tags';
		} finally {
			loading = false;
		}
	}

	function mbidChanged(): boolean {
		return MBID_FIELDS.some((f) => (form[f] ?? '') !== (original[f] ?? ''));
	}

	function close() {
		open = false;
		onClose?.();
	}

	async function submit() {
		if (mbidChanged() && !confirmMbid) {
			confirmMbid = true;
			return;
		}
		try {
			await save.mutateAsync({ fileId: track.id, releaseGroupMbid, tags: form });
			toastStore.show({ message: 'Tags updated', type: 'success' });
			close();
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to save tags',
				type: 'error'
			});
		}
	}
</script>

<dialog bind:this={dialogEl} class="modal modal-bottom sm:modal-middle" onclose={close}>
	<div class="modal-box max-w-lg">
		<h3 class="text-lg font-bold">Edit tags</h3>

		{#if loading}
			<div class="skeleton my-4 h-72 w-full"></div>
		{:else if loadError}
			<div class="alert alert-error my-4">{loadError}</div>
		{:else}
			<div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
				<label class="form-control sm:col-span-2">
					<span class="label-text text-xs">Title</span>
					<input class="input input-bordered input-sm" bind:value={form.title} />
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Artist</span>
					<input class="input input-bordered input-sm" bind:value={form.artist} />
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Album artist</span>
					<input class="input input-bordered input-sm" bind:value={form.album_artist} />
				</label>
				<label class="form-control sm:col-span-2">
					<span class="label-text text-xs">Album</span>
					<input class="input input-bordered input-sm" bind:value={form.album} />
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Year</span>
					<input type="number" class="input input-bordered input-sm" bind:value={form.year} />
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Genre</span>
					<input class="input input-bordered input-sm" bind:value={form.genre} />
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Track #</span>
					<input
						type="number"
						class="input input-bordered input-sm"
						bind:value={form.track_number}
					/>
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Disc #</span>
					<input
						type="number"
						class="input input-bordered input-sm"
						bind:value={form.disc_number}
					/>
				</label>

				<div class="divider sm:col-span-2 my-0 text-xs">MusicBrainz IDs</div>
				<label class="form-control sm:col-span-2">
					<span class="label-text text-xs">Release group</span>
					<input
						class="input input-bordered input-sm font-mono"
						bind:value={form.musicbrainz_release_group_id}
					/>
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Release</span>
					<input
						class="input input-bordered input-sm font-mono"
						bind:value={form.musicbrainz_release_id}
					/>
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Recording</span>
					<input
						class="input input-bordered input-sm font-mono"
						bind:value={form.musicbrainz_recording_id}
					/>
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Artist</span>
					<input
						class="input input-bordered input-sm font-mono"
						bind:value={form.musicbrainz_artist_id}
					/>
				</label>
				<label class="form-control">
					<span class="label-text text-xs">Album artist</span>
					<input
						class="input input-bordered input-sm font-mono"
						bind:value={form.musicbrainz_album_artist_id}
					/>
				</label>
			</div>

			{#if confirmMbid}
				<div class="alert alert-warning mt-3">
					<span class="text-sm">
						Changing MBIDs may affect library matching and future scans. Are you sure?
					</span>
				</div>
			{/if}
		{/if}

		<div class="modal-action">
			<button class="btn btn-ghost" onclick={close}>Cancel</button>
			<button class="btn btn-primary" onclick={submit} disabled={loading || save.isPending}>
				{#if save.isPending}<span class="loading loading-spinner loading-sm"></span>{/if}
				{confirmMbid ? 'Confirm save' : 'Save'}
			</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button onclick={close}>close</button>
	</form>
</dialog>
