<script lang="ts">
	import { ScanLine } from 'lucide-svelte';
	import { goto } from '$app/navigation';
	import { getLibraryScanStatusQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import { startLibraryScan } from '$lib/queries/library/LibraryMutations.svelte';
	import { toastStore } from '$lib/stores/toast';

	interface Props {
		class?: string;
		hasPath?: boolean;
		disabled?: boolean;
		title?: string;
	}
	let {
		class: className = 'btn btn-primary gap-1',
		hasPath = true,
		disabled = false,
		title
	}: Props = $props();

	const statusQuery = getLibraryScanStatusQuery();
	const scan = startLibraryScan();
	const isScanning = $derived(statusQuery.data?.status === 'scanning');

	async function handleClick() {
		if (!hasPath) {
			toastStore.show({ message: 'Add a library path first', type: 'info' });
			void goto('/settings?tab=library');
			return;
		}
		try {
			await scan.mutateAsync();
			toastStore.show({ message: 'Scan started', type: 'success' });
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to start scan',
				type: 'error'
			});
		}
	}
</script>

<button
	class={className}
	onclick={handleClick}
	disabled={disabled || isScanning || scan.isPending}
	{title}
>
	{#if isScanning}
		<span class="loading loading-spinner loading-sm"></span> Scanning…
	{:else}
		<ScanLine class="h-4 w-4" /> Start scan
	{/if}
</button>
