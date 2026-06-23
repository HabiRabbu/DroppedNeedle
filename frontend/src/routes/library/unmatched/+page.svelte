<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LibraryUnmatched from '$lib/components/library/LibraryUnmatched.svelte';
	import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
	import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';

	function refresh() {
		void invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.unmatched() });
	}
</script>

<svelte:head><title>Unmatched · Library</title></svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">
	<PageHeader
		subtitle="Files the scanner couldn't identify"
		breadcrumbs={[{ label: 'Library', href: '/library' }, { label: 'Unmatched' }]}
		onRefresh={refresh}
	>
		{#snippet title()}Unmatched files{/snippet}
	</PageHeader>
	<LibraryUnmatched />
</div>
