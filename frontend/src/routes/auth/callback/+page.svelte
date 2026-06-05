<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { onMount } from 'svelte';
	import { Music } from 'lucide-svelte';

	let error = $state<string | null>(null);

	onMount(async () => {
		const code = page.url.searchParams.get('code');
		if (!code) {
			error = 'Missing authentication code. Please try signing in again.';
			return;
		}
		try {
			const res = await fetch('/api/v1/auth/oidc/exchange', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ code }),
			});
			if (!res.ok) {
				error = 'Authentication failed. The link may have expired, please try again.';
				return;
			}
			const data = await res.json();
			authStore.setUser({
				id: data.user.id,
				display_name: data.user.display_name,
				role: data.user.role,
				email: data.user.email,
				avatar_url: data.user.avatar_url,
			});
			goto('/');
		} catch {
			error = 'Could not reach the server.';
		}
	});
</script>

<svelte:head>
	<title>Signing in - Musicseerr</title>
</svelte:head>

<div class="min-h-screen bg-base-100 flex items-center justify-center p-4">
	<div class="flex flex-col items-center gap-4 text-center">
		<div class="bg-primary/10 rounded-full p-4">
			<Music class="h-10 w-10 text-primary" />
		</div>

		{#if error}
			<div class="flex flex-col items-center gap-3 max-w-sm">
				<p class="text-base-content/70 text-sm">{error}</p>
				<a href="/login" class="btn btn-primary btn-sm">Back to sign in</a>
			</div>
		{:else}
			<p class="text-base-content/60 text-sm">Completing sign-in…</p>
			<span class="loading loading-spinner loading-md text-primary"></span>
		{/if}
	</div>
</div>
