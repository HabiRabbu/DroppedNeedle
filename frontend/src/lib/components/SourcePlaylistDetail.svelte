<script lang="ts">
	import { api } from '$lib/api/client';
	import BackButton from '$lib/components/BackButton.svelte';
	import { toastStore } from '$lib/stores/toast';
	import { formatTotalDurationSec } from '$lib/utils/formatting';
	import { Disc3, Download } from 'lucide-svelte';
	import type { SourcePlaylistDetail, SourceImportResult } from '$lib/types';
	import type { Snippet } from 'svelte';

	interface Props {
		playlistId: string;
		detailUrl: (id: string) => string;
		importUrl: (id: string) => string;
		backFallback: string;
		icon: Snippet;
	}

	let { playlistId, detailUrl, importUrl, backFallback, icon }: Props = $props();

	let detail = $state<SourcePlaylistDetail | null>(null);
	let loading = $state(true);
	let error = $state('');
	let importing = $state(false);
	let importResult = $state<SourceImportResult | null>(null);

	$effect(() => {
		if (playlistId) loadDetail(playlistId);
	});

	async function loadDetail(id: string) {
		loading = true;
		error = '';
		try {
			detail = await api.get<SourcePlaylistDetail>(detailUrl(id));
		} catch {
			error = "Couldn't load this playlist.";
		} finally {
			loading = false;
		}
	}

	async function handleImport() {
		if (!playlistId || importing) return;
		importing = true;
		try {
			importResult = await api.post<SourceImportResult>(importUrl(playlistId));
			if (importResult.already_imported) {
				toastStore.show({ message: 'This playlist is already in DroppedNeedle.', type: 'info' });
			} else {
				toastStore.show({
					message: `Imported ${importResult.tracks_imported} tracks into DroppedNeedle.`,
					type: 'success'
				});
			}
		} catch {
			toastStore.show({ message: "Couldn't import this playlist.", type: 'error' });
		} finally {
			importing = false;
		}
	}
</script>

<div class="max-w-4xl mx-auto px-4 py-6 space-y-6">
	<div class="flex items-center gap-3">
		<BackButton fallback={backFallback} />
		{@render icon()}
	</div>

	{#if loading}
		<div class="flex justify-center py-12">
			<span class="loading loading-spinner loading-lg"></span>
		</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else if detail}
		<div class="flex flex-col sm:flex-row gap-6">
			<div class="w-48 h-48 shrink-0 rounded-lg overflow-hidden shadow-md">
				{#if detail.cover_url}
					<img src={detail.cover_url} alt={detail.name} class="w-full h-full object-cover" />
				{:else}
					<div class="w-full h-full bg-base-200 flex items-center justify-center">
						<Disc3 class="w-16 h-16 text-base-content/20" />
					</div>
				{/if}
			</div>
			<div class="space-y-2">
				<h1 class="hero-title text-2xl font-bold">{detail.name}</h1>
				<p class="text-base-content/60">
					{detail.track_count} track{detail.track_count === 1 ? '' : 's'}
					{#if detail.duration_seconds}
						- {formatTotalDurationSec(detail.duration_seconds)}
					{/if}
				</p>
				<button
					class="btn btn-primary btn-sm gap-2"
					onclick={handleImport}
					disabled={importing || importResult?.already_imported}
				>
					{#if importing}
						<span class="loading loading-spinner loading-xs"></span>
					{:else}
						<Download class="w-4 h-4" />
					{/if}
					{importResult?.already_imported ? 'Already in DroppedNeedle' : 'Import into DroppedNeedle'}
				</button>
				{#if importResult && !importResult.already_imported}
					<p class="text-sm text-success">
						Imported {importResult.tracks_imported} tracks
						{#if importResult.tracks_failed > 0}
							({importResult.tracks_failed} skipped)
						{/if}
					</p>
				{/if}
			</div>
		</div>

		{#if detail.tracks.length > 0}
			<div class="overflow-x-auto">
				<table class="table table-sm">
					<thead>
						<tr>
							<th class="w-12">#</th>
							<th>Title</th>
							<th>Artist</th>
							<th>Album</th>
							<th class="text-right">Duration</th>
						</tr>
					</thead>
					<tbody>
						{#each detail.tracks as track, i (track.id)}
							<tr class="hover:bg-base-200/50">
								<td class="text-base-content/40">{i + 1}</td>
								<td class="font-medium">{track.track_name}</td>
								<td class="text-base-content/70">{track.artist_name}</td>
								<td class="text-base-content/70">{track.album_name}</td>
								<td class="text-right text-base-content/50">
									{#if track.duration_seconds}
										{Math.floor(track.duration_seconds / 60)}:{String(
											track.duration_seconds % 60
										).padStart(2, '0')}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
