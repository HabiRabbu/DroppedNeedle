<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LibraryReviewBrowser from '$lib/components/library/LibraryReviewBrowser.svelte';
</script>

<svelte:head><title>Identification review · DroppedNeedle</title></svelte:head>

<div class="min-h-[calc(100vh-200px)]">
	<PageHeader
		subtitle="Resolve uncertain album identities without interrupting playback"
		backHref="/library"
		backLabel="Back to library"
	>
		{#snippet title()}Identification review{/snippet}
	</PageHeader>
	<div class="mx-auto max-w-[96rem] px-4 pb-12 sm:px-6 lg:px-8">
		<LibraryReviewBrowser />
	</div>
</div>
