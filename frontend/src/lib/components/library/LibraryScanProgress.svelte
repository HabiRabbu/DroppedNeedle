<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { Check, Clock, ScanLine, TriangleAlert, X } from 'lucide-svelte';
	import { getLibraryScanStatusQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import { cancelLibraryScan } from '$lib/queries/library/LibraryMutations.svelte';
	import { createLibraryScanStream } from '$lib/queries/library/LibrarySSE.svelte';
	import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';
	import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { toastStore } from '$lib/stores/toast';

	const statusQuery = getLibraryScanStatusQuery();
	const scan = createLibraryScanStream();
	const cancel = cancelLibraryScan();

	let dismissed = $state(false);
	let sawLiveScan = $state(false);

	const polledScanning = $derived(statusQuery.data?.status === 'scanning');

	// scan.start() must run untracked to avoid re-triggering on its own $state writes.
	$effect(() => {
		if (polledScanning) {
			sawLiveScan = true;
			dismissed = false;
			untrack(() => scan.start());
		}
	});

	onDestroy(() => scan.stop());

	// Refresh library views when a scan finishes.
	let wasScanning = false;
	$effect(() => {
		const scanning = polledScanning;
		if (wasScanning && !scanning) {
			void invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all });
		}
		wasScanning = scanning;
	});

	const processed = $derived(scan.state.processed || statusQuery.data?.processed_files || 0);
	const total = $derived(scan.state.total || statusQuery.data?.total_files || 0);
	const matched = $derived(scan.state.matched || statusQuery.data?.matched_files || 0);
	const unmatched = $derived(scan.state.unmatched || 0);
	const percent = $derived(total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0);

	const showScanning = $derived(polledScanning || scan.state.status === 'scanning');
	const finalizing = $derived(scan.state.finalizing);
	const showComplete = $derived(
		!showScanning && sawLiveScan && !dismissed && scan.state.status === 'complete'
	);
	const showFailed = $derived(
		!showScanning && sawLiveScan && !dismissed && scan.state.status === 'failed'
	);

	let nowMs = $state(Date.now());
	$effect(() => {
		if (!showScanning) return;
		const id = setInterval(() => (nowMs = Date.now()), 1000);
		return () => clearInterval(id);
	});
	const startedAt = $derived(statusQuery.data?.started_at ?? null);
	const elapsedLabel = $derived.by(() => {
		if (!startedAt) return null;
		const secs = Math.max(0, Math.floor(nowMs / 1000 - startedAt));
		const m = Math.floor(secs / 60);
		const s = secs % 60;
		return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
	});

	async function handleCancel() {
		try {
			await cancel.mutateAsync();
		} catch {
			toastStore.show({ message: 'Failed to cancel scan', type: 'error' });
		}
	}
</script>

{#if showScanning}
	<div
		class="scan-banner relative mb-4 overflow-hidden rounded-box border border-primary/25 bg-base-200 shadow-sm"
		role="progressbar"
		aria-valuenow={percent}
		aria-valuemin={0}
		aria-valuemax={100}
		aria-label="Library scan progress"
		aria-live="polite"
	>
		<div class="scan-water" style="width: {percent}%" aria-hidden="true">
			<div class="scan-wave"></div>
		</div>

		<div class="relative z-10 flex flex-col gap-4 p-4 sm:p-5">
			<div class="flex items-center gap-3">
				<div
					class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/10 ring-1 ring-primary/20"
				>
					<div class="flex h-4 items-end gap-[3px]" aria-hidden="true">
						<span class="scan-eq scan-eq-1 w-[3px] rounded-full bg-primary"></span>
						<span class="scan-eq scan-eq-2 w-[3px] rounded-full bg-primary"></span>
						<span class="scan-eq scan-eq-3 w-[3px] rounded-full bg-primary"></span>
						<span class="scan-eq scan-eq-1 w-[3px] rounded-full bg-primary"></span>
					</div>
				</div>

				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-1.5">
						<ScanLine class="h-4 w-4 text-primary" />
						<h3 class="font-semibold">{finalizing ? 'Finalising library' : 'Scanning library'}</h3>
					</div>
					<p class="text-xs text-base-content/55">
						{#if finalizing}
							Resolving artists - {finalizing.remaining.toLocaleString()} remaining
						{:else}
							{processed.toLocaleString()} of {total ? total.toLocaleString() : '…'} files
						{/if}
					</p>
				</div>

				<div class="flex items-center gap-3 sm:gap-4">
					<div class="leading-none">
						<span class="text-3xl font-bold tabular-nums sm:text-4xl">{percent}</span><span
							class="text-lg font-semibold text-base-content/40">%</span
						>
					</div>
					{#if authStore.isAdmin}
						<button class="btn btn-ghost btn-sm" onclick={handleCancel} disabled={cancel.isPending}>
							{#if cancel.isPending}<span class="loading loading-spinner loading-xs"></span>{/if}
							Cancel
						</button>
					{/if}
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
				<span class="flex items-center gap-1.5">
					<span class="h-2 w-2 rounded-full bg-accent"></span>
					<span class="font-semibold tabular-nums">{matched.toLocaleString()}</span>
					<span class="text-base-content/55">matched</span>
				</span>
				<span class="flex items-center gap-1.5">
					<span class="h-2 w-2 rounded-full bg-warning"></span>
					<span class="font-semibold tabular-nums">{unmatched.toLocaleString()}</span>
					<span class="text-base-content/55">for review</span>
				</span>
				{#if elapsedLabel}
					<span class="flex items-center gap-1.5 text-base-content/55">
						<Clock class="h-3.5 w-3.5" />
						<span class="tabular-nums">{elapsedLabel} elapsed</span>
					</span>
				{/if}
				{#if scan.state.errorMessage}
					<span class="text-warning">{scan.state.errorMessage}</span>
				{/if}
			</div>
		</div>
	</div>
{:else if showComplete}
	<div
		class="alert animate-fade-in-up mb-4 {scan.state.warning ? 'alert-warning' : 'alert-success'}"
	>
		{#if scan.state.warning}
			<TriangleAlert class="h-5 w-5 shrink-0" />
		{:else}
			<Check class="h-5 w-5 shrink-0" />
		{/if}
		<span>
			Scan complete: {matched.toLocaleString()} matched, {unmatched.toLocaleString()} queued for review.{#if scan.state.warning}<br
				/><span class="text-sm">{scan.state.warning}</span>{/if}
		</span>
		<button
			class="btn btn-ghost btn-xs btn-circle"
			onclick={() => (dismissed = true)}
			aria-label="Dismiss"
		>
			<X class="h-3.5 w-3.5" />
		</button>
	</div>
{:else if showFailed}
	<div class="alert alert-error animate-fade-in-up mb-4">
		<TriangleAlert class="h-5 w-5" />
		<span>Scan failed: {scan.state.errorMessage}</span>
		<button
			class="btn btn-ghost btn-xs btn-circle"
			onclick={() => (dismissed = true)}
			aria-label="Dismiss"
		>
			<X class="h-3.5 w-3.5" />
		</button>
	</div>
{/if}

<style>
	.scan-banner {
		animation: var(--animate-fade-in-up);
	}

	.scan-water {
		position: absolute;
		top: 0;
		bottom: 0;
		left: 0;
		min-width: 0;
		pointer-events: none;
		background: linear-gradient(
			90deg,
			oklch(from var(--color-primary) l c h / 0.16),
			oklch(from var(--color-accent) l c h / 0.24)
		);
		background-size: 220% 100%;
		animation: var(--animate-gradient-shift);
		transition: width 1800ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.scan-wave {
		position: absolute;
		top: -8px;
		bottom: -8px;
		right: -18px;
		width: 36px;
		background: linear-gradient(
			90deg,
			oklch(from var(--color-accent) l c h / 0.32),
			oklch(from var(--color-primary) l c h / 0.14) 55%,
			transparent
		);
		-webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='36' height='48'%3E%3Cpath d='M0,0 C18,10 18,14 0,24 C18,34 18,38 0,48 L36,48 L36,0 Z' fill='black'/%3E%3C/svg%3E")
			repeat-y;
		mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='36' height='48'%3E%3Cpath d='M0,0 C18,10 18,14 0,24 C18,34 18,38 0,48 L36,48 L36,0 Z' fill='black'/%3E%3C/svg%3E")
			repeat-y;
		-webkit-mask-size: 36px 48px;
		mask-size: 36px 48px;
		animation: scan-wave-drift 3.2s linear infinite;
	}

	@keyframes scan-wave-drift {
		to {
			-webkit-mask-position: 0 48px;
			mask-position: 0 48px;
		}
	}

	.scan-eq-1 {
		animation: var(--animate-equalizer-1);
	}
	.scan-eq-2 {
		animation: var(--animate-equalizer-2);
	}
	.scan-eq-3 {
		animation: var(--animate-equalizer-3);
	}

	@media (prefers-reduced-motion: reduce) {
		.scan-banner,
		.scan-water,
		.scan-wave,
		.scan-eq-1,
		.scan-eq-2,
		.scan-eq-3 {
			animation: none;
		}
		.scan-water {
			transition: none;
		}
	}
</style>
