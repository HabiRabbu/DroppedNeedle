<script lang="ts">
	import { RotateCcw } from 'lucide-svelte';
	import { getLibraryScanStatusQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import { startForceLibraryScan } from '$lib/queries/library/LibraryMutations.svelte';
	import LibraryForceRescanModal from '$lib/components/library/LibraryForceRescanModal.svelte';
	import { toastStore } from '$lib/stores/toast';

	interface Props {
		hasPath?: boolean;
		class?: string;
	}
	let { hasPath = true, class: className = 'btn btn-outline btn-error gap-1' }: Props = $props();

	const statusQuery = getLibraryScanStatusQuery();
	const forceScan = startForceLibraryScan();
	const isScanning = $derived(statusQuery.data?.status === 'scanning');
	let modal = $state<ReturnType<typeof LibraryForceRescanModal> | null>(null);

	async function handleForceRescan() {
		try {
			await forceScan.mutateAsync();
			toastStore.show({ message: 'Full re-scan started', type: 'success' });
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to start re-scan',
				type: 'error'
			});
		} finally {
			modal?.close();
		}
	}
</script>

<button
	class={className}
	onclick={() => modal?.showModal()}
	disabled={!hasPath || isScanning || forceScan.isPending}
	title={!hasPath
		? 'Add a library path first'
		: 'Re-identify every file and clear the MusicBrainz cache'}
>
	<RotateCcw class="h-4 w-4" /> Force full re-scan
</button>

<LibraryForceRescanModal
	bind:this={modal}
	scanning={forceScan.isPending}
	onconfirm={handleForceRescan}
/>
