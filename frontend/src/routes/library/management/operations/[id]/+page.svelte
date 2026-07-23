<script lang="ts">
	import { page } from '$app/state';
	import LibraryManagementOperationPage from '$lib/components/library/LibraryManagementOperationPage.svelte';

	const jobId = $derived(page.params.id ?? '');
</script>

<LibraryManagementOperationPage {jobId} />
