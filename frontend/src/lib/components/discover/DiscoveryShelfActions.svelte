<script lang="ts">
	import { Download } from 'lucide-svelte';
	import DiscoveryBatchModal from '$lib/components/discover/DiscoveryBatchModal.svelte';
	import RadioPlayButton from '$lib/components/discover/RadioPlayButton.svelte';
	import { integrationStore } from '$lib/stores/integration';
	import { libraryStore } from '$lib/stores/library';
	import type { HomeAlbum, HomeSection, RadioPlanRequest } from '$lib/types';

	interface Props {
		section: HomeSection;
		sectionKey: string;
		seed: Omit<RadioPlanRequest, 'exclude_recording_mbids' | 'fast'>;
	}

	let { section, sectionKey, seed }: Props = $props();
	let batchModalOpen = $state(false);

	const albums = $derived(
		section.type === 'albums' ? (section.items as HomeAlbum[]) : ([] as HomeAlbum[])
	);
	const requestableCount = $derived(
		albums.filter(
			(album) =>
				album.mbid && !album.in_library && !album.requested && !libraryStore.isRequested(album.mbid)
		).length
	);
	const canDownload = $derived($integrationStore.download_client && requestableCount > 0);
</script>

<div class="flex flex-wrap items-center gap-2">
	<RadioPlayButton {seed} size="sm" label="Play all" />
	{#if canDownload}
		<button
			type="button"
			class="btn btn-outline btn-sm gap-2"
			onclick={() => (batchModalOpen = true)}
			title="Request every album you don't own"
		>
			<Download class="h-4 w-4" />
			Download all
		</button>
	{/if}
</div>

{#if canDownload}
	<DiscoveryBatchModal
		bind:open={batchModalOpen}
		sectionTitle={section.title}
		{sectionKey}
		{albums}
	/>
{/if}
