<script lang="ts">
	import { Disc3, Play, Loader2, RefreshCw } from 'lucide-svelte';
	import { getQueueCachedData, subscribeQueueCacheChanges } from '$lib/utils/discoverQueueCache';
	import type { MusicSource } from '$lib/stores/musicSource';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { discoverQueueStatusStore, type QueueBuildStatus } from '$lib/stores/discoverQueueStatus';

	let { onLaunch, source }: { onLaunch: () => void; source: MusicSource } = $props();

	let bgStatus = $state<QueueBuildStatus>('unknown');

	function recheckCachedQueue() {
		const cached = getQueueCachedData(authStore.user?.id ?? 'anon', source);
		return (cached?.data?.items?.length ?? 0) > 0;
	}

	let hasCachedQueue = $derived.by(() => {
		return recheckCachedQueue();
	});

	$effect(() => {
		const unsubStatus = discoverQueueStatusStore.subscribe((s) => {
			bgStatus = s.status;
			hasCachedQueue = recheckCachedQueue();
		});
		return unsubStatus;
	});

	$effect(() => {
		const unsubscribeCache = subscribeQueueCacheChanges((changedSource) => {
			if (!changedSource || changedSource === source) {
				hasCachedQueue = recheckCachedQueue();
			}
		});
		return unsubscribeCache;
	});

	let isBuilding = $derived(bgStatus === 'building');
	let isReady = $derived(bgStatus === 'ready' && !hasCachedQueue);
	let isError = $derived(bgStatus === 'error');

	function handleRetry() {
		discoverQueueStatusStore.triggerGenerate(true, source);
	}
</script>

<div
	class="card card-border bg-linear-to-br from-primary/10 via-secondary/8 to-accent/6 w-full shadow-sm relative overflow-hidden
		{isReady ? 'animate-glow-pulse' : ''}"
	class:glow-primary-strong={isReady}
>
	<div
		class="absolute inset-0 rounded-[inherit] pointer-events-none"
		style="border: 2px dashed rgb(var(--brand-discover) / 0.25); border-radius: inherit;"
	></div>
	<div class="card-body items-center gap-5 py-12 text-center">
		<div class="text-base-content/20">
			{#if isBuilding && !hasCachedQueue}
				<div class="flex items-end gap-0.75 h-10 w-10 justify-center pb-1">
					<span class="w-1.5 bg-primary rounded-full animate-equalizer-1" style="height: 60%;"
					></span>
					<span class="w-1.5 bg-primary rounded-full animate-equalizer-2" style="height: 80%;"
					></span>
					<span class="w-1.5 bg-primary rounded-full animate-equalizer-3" style="height: 40%;"
					></span>
					<span
						class="w-1.5 bg-primary rounded-full animate-equalizer-1"
						style="height: 70%; animation-delay: 0.2s;"
					></span>
				</div>
			{:else}
				<Disc3 class="h-10 w-10" strokeWidth={1.5} />
			{/if}
		</div>
		<div class="flex flex-col gap-1">
			<h3 class="text-xl font-bold text-base-content">Discover Queue</h3>
			{#if hasCachedQueue}
				<p class="text-sm text-base-content/60">You have a queue in progress</p>
			{:else if isBuilding}
				<p class="text-sm text-base-content/60">Building your personalised queue…</p>
			{:else if isError}
				<p class="text-sm text-error/80">We couldn't build your queue</p>
			{:else if isReady}
				<p class="text-sm text-success/80">Your queue is ready!</p>
			{:else}
				<p class="text-sm text-base-content/60">Find new music tailored to your taste</p>
			{/if}
		</div>
		<div class="flex gap-2">
			{#if hasCachedQueue}
				<button class="btn btn-primary btn-lg" onclick={onLaunch}>
					<Play class="h-5 w-5" strokeWidth={2} />
					Resume Discover Queue
				</button>
			{:else if isBuilding}
				<button class="btn btn-primary btn-lg btn-disabled" disabled>
					<Loader2 class="h-5 w-5 animate-spin" strokeWidth={2} />
					Building…
				</button>
			{:else if isError}
				<button class="btn btn-error btn-outline btn-lg" onclick={handleRetry}>
					<RefreshCw class="h-5 w-5" strokeWidth={2} />
					Retry
				</button>
				<button class="btn btn-primary btn-lg" onclick={onLaunch}>
					<Play class="h-5 w-5" strokeWidth={2} />
					Launch Anyway
				</button>
			{:else}
				<button class="btn btn-primary btn-lg" onclick={onLaunch}>
					<Play class="h-5 w-5" strokeWidth={2} />
					Launch Discover Queue
				</button>
			{/if}
		</div>
	</div>
</div>
