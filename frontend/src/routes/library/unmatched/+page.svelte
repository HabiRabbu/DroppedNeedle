<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => void goto('/library/review', { replaceState: true }));
</script>

<svelte:head><title>Identification review · DroppedNeedle</title></svelte:head>
