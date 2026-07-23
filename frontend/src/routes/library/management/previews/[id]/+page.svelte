<script lang="ts">
	import { page } from '$app/state';
	import LibraryManagementPreviewPage from '$lib/components/library/LibraryManagementPreviewPage.svelte';

	const jobId = $derived(page.params.id ?? '');
</script>

<LibraryManagementPreviewPage {jobId} />
