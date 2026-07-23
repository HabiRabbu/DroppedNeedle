<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import {
		AlertTriangle,
		ArrowLeft,
		CirclePause,
		CirclePlay,
		Clock3,
		FolderCog,
		History,
		OctagonX,
		RotateCcw,
		ServerCog,
		ShieldAlert
	} from 'lucide-svelte';

	import { authStore } from '$lib/stores/authStore.svelte';
	import { createLibraryManagementEvents } from '$lib/queries/library-management/LibraryManagementEvents';
	import {
		controlLibraryManagementOperationMutation,
		createLibraryManagementUndoPreviewMutation
	} from '$lib/queries/library-management/LibraryManagementMutations.svelte';
	import {
		getLibraryManagementOperationQuery,
		getLibraryManagementOperationResultsQuery
	} from '$lib/queries/library-management/LibraryManagementQueries.svelte';
	import { rememberLibraryManagementPreviewToken } from '$lib/queries/library-management/LibraryManagementPreviewTokens';
	import { createUuid } from '$lib/utils/uuid';
	import {
		formatManagementValue,
		managementAudioFormat,
		titleManagementValue
	} from './LibraryManagementDisplay';

	interface Props {
		jobId: string;
	}

	let { jobId }: Props = $props();
	let stopDialog: HTMLDialogElement;
	let stopHeading: HTMLHeadingElement;
	let stopOpener: HTMLButtonElement | null = null;
	let undoDialog: HTMLDialogElement;
	let undoHeading: HTMLHeadingElement;
	let undoOpener: HTMLButtonElement | null = null;
	let undoError = $state('');

	const operationQuery = getLibraryManagementOperationQuery(
		() => authStore.user?.id,
		() => jobId
	);
	const resultsQuery = getLibraryManagementOperationResultsQuery(
		() => authStore.user?.id,
		() => jobId,
		() => 50
	);
	const pauseOperation = controlLibraryManagementOperationMutation('pause');
	const resumeOperation = controlLibraryManagementOperationMutation('resume');
	const stopOperation = controlLibraryManagementOperationMutation('stop');
	const createUndo = createLibraryManagementUndoPreviewMutation();

	const operation = $derived(operationQuery.data ?? null);
	const externalRefreshes = $derived(operation?.external_refreshes ?? []);
	const results = $derived(resultsQuery.data?.pages.flatMap((page) => page.items) ?? []);
	const activePhaseLabel = $derived.by(() => {
		if (!operation) return 'Loading';
		const states = new Set(results.flatMap((item) => item.journal_states));
		if (states.has('cleanup_pending') || states.has('catalog_committed')) return 'Cleaning up';
		if (states.has('published')) return 'Committing catalog';
		if (states.has('source_backed_up') || states.has('validated')) return 'Publishing files';
		if (states.has('staged')) return 'Validating staged files';
		if (states.has('snapshot_saved')) return 'Writing staged files';
		if (states.has('planned')) return 'Preparing snapshots';
		return titleManagementValue(operation.phase);
	});
	const progress = $derived(
		operation && operation.expected_work_count > 0
			? Math.min(100, Math.round((operation.completed_count / operation.expected_work_count) * 100))
			: 0
	);
	const undoAvailable = $derived(
		Boolean(
			operation &&
			['succeeded', 'stopped'].includes(operation.state) &&
			operation.succeeded_count > 0
		)
	);

	onMount(() => {
		const events = createLibraryManagementEvents();
		events.start();
		return events.stop;
	});

	async function control(action: 'pause' | 'resume'): Promise<void> {
		if (!operation) return;
		const mutation = action === 'pause' ? pauseOperation : resumeOperation;
		await mutation
			.mutateAsync({ jobId, expectedRevision: operation.operation_row_revision })
			.catch(() => undefined);
	}

	async function stop(): Promise<void> {
		if (!operation) return;
		try {
			await stopOperation.mutateAsync({
				jobId,
				expectedRevision: operation.operation_row_revision
			});
			stopDialog.close();
		} catch {
			return;
		}
	}

	async function previewUndo(): Promise<void> {
		if (!operation || !undoAvailable) return;
		undoError = '';
		try {
			const handle = await createUndo.mutateAsync({
				jobId,
				request: {
					expected_operation_row_revision: operation.operation_row_revision,
					idempotency_key: createUuid()
				}
			});
			rememberLibraryManagementPreviewToken(handle.job_id, handle.preview_token);
			undoDialog.close();
			await goto(`/library/management/previews/${encodeURIComponent(handle.job_id)}`);
		} catch (error) {
			undoError = error instanceof Error ? error.message : 'Could not create the undo preview.';
		}
	}

	function formatDate(value: number): string {
		return new Date(value * 1000).toLocaleString();
	}

	function refreshStatusCopy(state: string): string {
		if (state === 'succeeded') return 'Refresh request accepted by the media server.';
		if (state === 'delivering') return 'Sending the refresh request now.';
		if (state === 'retry_wait') return 'The last request failed; a durable retry is scheduled.';
		if (state === 'failed') return 'Refresh attempts ended without acknowledgement.';
		if (state === 'unavailable') return 'This integration is unavailable or not configured.';
		return 'Waiting for the operation worker.';
	}
</script>

<svelte:head><title>Library Management operation · DroppedNeedle</title></svelte:head>

<div class="management-preview-shell px-4 py-8 sm:px-6 lg:px-8">
	<main class="mx-auto max-w-6xl space-y-5">
		<a href="/library#operations" class="btn btn-ghost btn-sm -ml-2"
			><ArrowLeft class="h-4 w-4" /> Library control room</a
		>

		{#if operationQuery.isLoading}
			<div class="space-y-4">
				<div class="skeleton h-48 rounded-2xl"></div>
				<div class="skeleton h-72 rounded-2xl"></div>
			</div>
		{:else if operationQuery.isError}
			<div class="alert alert-error">Could not load this Library Management operation.</div>
		{:else if operation}
			<header class="management-control-room p-5 sm:p-7">
				<div class="flex flex-wrap items-start gap-4">
					<div class="management-write-mark"><FolderCog class="h-6 w-6" /></div>
					<div class="min-w-0 flex-1">
						<p class="management-kicker">
							<ShieldAlert class="h-3.5 w-3.5" /> File-writing operation
						</p>
						<h1 class="mt-1 font-display text-2xl font-bold sm:text-3xl">
							{titleManagementValue(operation.mode)}
						</h1>
						<p class="mt-2 text-sm text-base-content/60">
							{operation.profile_name} · {titleManagementValue(operation.origin)} · started {formatDate(
								operation.created_at
							)}
						</p>
					</div>
					<span
						class="badge badge-lg {operation.state === 'failed'
							? 'badge-error'
							: operation.state === 'succeeded'
								? 'badge-success'
								: operation.state === 'paused'
									? 'badge-warning'
									: 'badge-outline'}">{titleManagementValue(operation.state)}</span
					>
				</div>
				<div class="mt-5">
					<div class="mb-2 flex justify-between text-xs">
						<span>{activePhaseLabel}</span><span
							>{operation.completed_count.toLocaleString()} / {operation.expected_work_count.toLocaleString()}</span
						>
					</div>
					<progress
						class="progress progress-warning w-full"
						value={progress}
						max="100"
						aria-label={`${progress}% complete`}
					></progress>
				</div>
				<div class="mt-4 grid gap-2 sm:grid-cols-4">
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Succeeded</span><strong
							>{operation.succeeded_count}</strong
						>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Failed</span><strong
							>{operation.failed_count}</strong
						>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Skipped</span><strong
							>{operation.skipped_count}</strong
						>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Revision</span><strong
							>{operation.operation_row_revision}</strong
						>
					</div>
				</div>
				{#if ['queued', 'running', 'paused'].includes(operation.state)}<div
						class="mt-4 flex flex-wrap gap-2"
					>
						{#if operation.state === 'paused'}<button
								class="btn management-btn btn-sm"
								disabled={resumeOperation.isPending}
								onclick={() => void control('resume')}
								>{#if resumeOperation.isPending}<span class="loading loading-spinner loading-sm"
									></span>{/if}<CirclePlay class="h-4 w-4" /> Resume</button
							>{:else if operation.state === 'running'}<button
								class="btn btn-outline btn-sm"
								disabled={pauseOperation.isPending}
								onclick={() => void control('pause')}
								>{#if pauseOperation.isPending}<span class="loading loading-spinner loading-sm"
									></span>{/if}<CirclePause class="h-4 w-4" /> Pause</button
							>{/if}<button
							class="btn btn-ghost btn-sm text-error"
							onclick={(event) => {
								stopOpener = event.currentTarget;
								stopDialog.showModal();
								stopHeading.focus();
							}}><OctagonX class="h-4 w-4" /> Stop...</button
						>
					</div>{/if}
			</header>

			{#if operation.terminal_code}<div class="alert alert-error">
					<AlertTriangle class="h-5 w-5" /><span
						><strong>{titleManagementValue(operation.terminal_code)}</strong><br />Inspect per-file
						results below. Recovery never silently removes an uncertain file.</span
					>
				</div>{/if}

			{#if externalRefreshes.length}<section class="management-operation-panel">
					<div class="flex items-start gap-3">
						<div class="mt-0.5 rounded-lg border border-base-content/10 bg-base-200/60 p-2">
							<ServerCog class="h-4 w-4 text-library-manage" />
						</div>
						<div>
							<p class="management-step">Post-commit refresh</p>
							<h2 class="font-display text-xl font-semibold">Media-server delivery ledger</h2>
							<p class="mt-1 text-sm text-base-content/55">
								These requests happen after the file and catalog transaction. A refresh failure
								never rolls those changes back.
							</p>
						</div>
					</div>
					<div class="mt-4 divide-y divide-base-content/10 border-y border-base-content/10">
						{#each externalRefreshes as delivery (delivery.target)}<div
								class="grid gap-2 py-3 sm:grid-cols-[10rem_1fr_auto] sm:items-center"
							>
								<strong>{titleManagementValue(delivery.target)}</strong>
								<div>
									<p class="text-sm text-base-content/65">{refreshStatusCopy(delivery.state)}</p>
									<p class="mt-0.5 text-xs text-base-content/45">
										{delivery.attempts} of {delivery.max_attempts} attempts used{#if delivery.failure_code}
											· {titleManagementValue(delivery.failure_code)}{/if}
									</p>
								</div>
								<span
									class="badge badge-sm {delivery.state === 'succeeded'
										? 'badge-success'
										: ['failed', 'unavailable'].includes(delivery.state)
											? 'badge-error'
											: delivery.state === 'retry_wait'
												? 'badge-warning'
												: 'badge-outline'}">{titleManagementValue(delivery.state)}</span
								>
							</div>{/each}
					</div>
				</section>{/if}

			<section class="management-operation-panel space-y-3">
				<div class="flex flex-wrap items-end justify-between gap-2">
					<div>
						<p class="management-step">Durable audit trail</p>
						<h2 class="font-display text-xl font-semibold">Per-file results</h2>
					</div>
					<a href="/library/management/history" class="btn btn-ghost btn-sm"
						><History class="h-4 w-4" /> All history</a
					>
				</div>
				{#if resultsQuery.isLoading}<div class="space-y-2">
						<div class="skeleton h-20"></div>
						<div class="skeleton h-20"></div>
					</div>{:else if resultsQuery.isError}<div class="alert alert-error">
						Could not load operation results.
					</div>{:else if results.length === 0}<div
						class="rounded-xl border border-dashed border-base-content/15 p-5 text-sm text-base-content/50"
					>
						No per-file results have been recorded yet.
					</div>{:else}<div class="space-y-2">
						{#each results as item (`${item.plan.ordinal}:${item.work_state}`)}<article
								class="rounded-xl border border-base-content/10 p-3"
							>
								<div class="flex flex-wrap items-start justify-between gap-2">
									<div>
										<strong
											>{item.plan.source_relative_path?.split('/').at(-1) ??
												`Item ${item.plan.ordinal + 1}`}</strong
										>
										<p class="text-xs text-base-content/50">
											{managementAudioFormat(item.plan).toUpperCase()} · bundle {item.plan
												.bundle_ordinal + 1}
										</p>
									</div>
									<span
										class="badge badge-sm {item.failure_code
											? 'badge-error'
											: item.work_state === 'succeeded' || item.work_state === 'completed'
												? 'badge-success'
												: 'badge-outline'}"
										>{titleManagementValue(item.failure_code ?? item.work_state)}</span
									>
								</div>
								{#if item.journal_states.length}<p class="mt-2 text-xs text-base-content/50">
										Journal: {item.journal_states.map(titleManagementValue).join(' → ')}
									</p>{/if}{#if Object.keys(item.result).length}<details class="mt-2 text-sm">
										<summary class="cursor-pointer font-semibold">Result evidence</summary>
										<p class="mt-2 break-words font-mono text-xs text-base-content/60">
											{formatManagementValue(item.result)}
										</p>
									</details>{/if}
							</article>{/each}
					</div>
					{#if resultsQuery.hasNextPage}<button
							class="btn btn-outline w-full"
							disabled={resultsQuery.isFetchingNextPage}
							onclick={() => void resultsQuery.fetchNextPage()}
							>{#if resultsQuery.isFetchingNextPage}<span class="loading loading-spinner loading-sm"
								></span>{/if} Load more results</button
						>{/if}{/if}
			</section>

			<section class="grid gap-3 sm:grid-cols-2">
				<div class="management-operation-panel">
					<RotateCcw class="h-5 w-5 text-library-manage" />
					<h2 class="mt-2 font-semibold">Undo this operation</h2>
					<p class="mt-1 text-sm text-base-content/55">
						Creates a separate preview from this operation's before-state snapshots. Files changed
						again later are skipped.
					</p>
					<button
						class="btn btn-outline btn-sm mt-3"
						disabled={!undoAvailable}
						onclick={(event) => {
							undoOpener = event.currentTarget;
							undoError = '';
							undoDialog.showModal();
							undoHeading.focus();
						}}>Preview Undo...</button
					>{#if !undoAvailable}<p class="mt-2 text-xs text-base-content/45">
							Undo appears after a successful or stopped operation with completed changes.
						</p>{/if}
				</div>
				<div class="management-operation-panel">
					<Clock3 class="h-5 w-5 text-base-content/50" />
					<h2 class="mt-2 font-semibold">First-management baseline</h2>
					<p class="mt-1 text-sm text-base-content/55">
						Restore files to how they were before DroppedNeedle first managed them. This is broader
						than Undo and leaves restored files unmanaged.
					</p>
					<a href="/library#operations" class="btn btn-ghost btn-sm mt-3"
						>Open baseline restore...</a
					>
				</div>
			</section>
		{/if}
	</main>
</div>

<dialog
	bind:this={stopDialog}
	class="modal"
	aria-labelledby="stop-management-title"
	onclose={() => stopOpener?.focus()}
	oncancel={(event) => {
		if (stopOperation.isPending) event.preventDefault();
	}}
>
	<div class="modal-box max-w-md">
		<h2
			bind:this={stopHeading}
			id="stop-management-title"
			tabindex="-1"
			class="font-display text-xl font-semibold"
		>
			Stop after the current safe boundary?
		</h2>
		<p class="mt-3 text-sm text-base-content/65">
			Stopping keeps completed changes. It does not roll them back. Use Undo after the job finishes
			or stops.
		</p>
		<div class="modal-action">
			<button
				class="btn btn-ghost"
				disabled={stopOperation.isPending}
				onclick={() => stopDialog.close()}>Keep working</button
			><button class="btn btn-error" disabled={stopOperation.isPending} onclick={() => void stop()}
				>{#if stopOperation.isPending}<span class="loading loading-spinner loading-sm"></span>{/if} Stop
				operation</button
			>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button aria-label="Cancel stopping management operation" disabled={stopOperation.isPending}
			>close</button
		>
	</form>
</dialog>

<dialog
	bind:this={undoDialog}
	class="modal"
	aria-labelledby="undo-management-title"
	onclose={() => undoOpener?.focus()}
	oncancel={(event) => {
		if (createUndo.isPending) event.preventDefault();
	}}
>
	<div class="modal-box max-w-md">
		<p class="management-kicker">Operation-specific recovery</p>
		<h2
			bind:this={undoHeading}
			id="undo-management-title"
			tabindex="-1"
			class="font-display text-xl font-semibold"
		>
			Generate an Undo preview?
		</h2>
		<p class="mt-3 text-sm text-base-content/65">
			This does not immediately change files. A full preview will show restorable, changed, expired,
			and blocked items before a separate Apply confirmation.
		</p>
		<div class="mt-3 alert alert-info text-sm">
			<RotateCcw class="h-5 w-5" /><span
				><strong>Undo is not baseline restore.</strong> It targets only this operation's completed changes.</span
			>
		</div>
		{#if undoError}<div class="alert alert-error mt-3 text-sm" role="alert">{undoError}</div>{/if}
		<div class="modal-action">
			<button
				class="btn btn-ghost"
				disabled={createUndo.isPending}
				onclick={() => undoDialog.close()}>Cancel</button
			><button
				class="btn management-btn"
				disabled={createUndo.isPending || !undoAvailable}
				onclick={() => void previewUndo()}
				>{#if createUndo.isPending}<span class="loading loading-spinner loading-sm"></span>{/if} Generate
				Undo preview</button
			>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button aria-label="Cancel undo preview" disabled={createUndo.isPending}>close</button>
	</form>
</dialog>
