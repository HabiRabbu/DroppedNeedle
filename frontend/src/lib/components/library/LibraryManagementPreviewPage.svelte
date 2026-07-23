<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import {
		ArrowLeft,
		ArrowRight,
		CheckCircle2,
		ChevronRight,
		Clock3,
		FolderCog,
		HardDrive,
		Layers3,
		ShieldAlert,
		Sparkles,
		Tags,
		X
	} from 'lucide-svelte';

	import { getTargetLibrarySettingsQuery } from '$lib/queries/library/LibraryPolicyQueries.svelte';
	import { getLibrarySearchQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { createLibraryManagementEvents } from '$lib/queries/library-management/LibraryManagementEvents';
	import {
		applyLibraryManagementPreviewMutation,
		createLibraryManagementDuplicateResolutionMutation
	} from '$lib/queries/library-management/LibraryManagementMutations.svelte';
	import {
		getLibraryManagementPlanItemsQuery,
		getLibraryManagementPreviewQuery,
		getLibraryManagementSettingsQuery
	} from '$lib/queries/library-management/LibraryManagementQueries.svelte';
	import {
		forgetLibraryManagementPreviewToken,
		readLibraryManagementPreviewToken,
		rememberLibraryManagementPreviewToken
	} from '$lib/queries/library-management/LibraryManagementPreviewTokens';
	import type {
		DuplicateResolutionAction,
		LibraryManagementPlanItem,
		ManagementChangeKind,
		ManagementEligibility
	} from '$lib/queries/library-management/types';
	import { createUuid } from '$lib/utils/uuid';
	import {
		formatManagementValue,
		isRecord,
		managementAdapter,
		managementAudioFormat,
		managementCollisions,
		managementCustomTagDiffs,
		managementFieldDiffs,
		managementSidecars,
		managementStringList,
		titleManagementValue,
		type ManagementCollision
	} from './LibraryManagementDisplay';

	interface Props {
		jobId: string;
	}

	interface CollisionSelection {
		item: LibraryManagementPlanItem;
		collision: ManagementCollision;
	}

	let { jobId }: Props = $props();
	let eligibility = $state<ManagementEligibility | ''>('');
	let reasonCode = $state('');
	let rootId = $state('');
	let artistId = $state('');
	let artistLabel = $state('');
	let albumId = $state('');
	let albumLabel = $state('');
	let catalogSearch = $state('');
	let audioFormat = $state('');
	let changeKind = $state<ManagementChangeKind | ''>('');
	let collisionClass = $state('');
	let hasPreservedValue = $state(false);
	let hasRepresentationLoss = $state(false);
	let previewToken = $state<string | null>(null);
	let confirmation = $state('');
	let applyError = $state('');
	let applyDialog: HTMLDialogElement;
	let applyHeading: HTMLHeadingElement;
	let applyOpener: HTMLButtonElement | null = null;
	let collisionDialog: HTMLDialogElement;
	let collisionHeading: HTMLHeadingElement;
	let collisionOpener: HTMLButtonElement | null = null;
	let collisionSelection = $state<CollisionSelection | null>(null);
	let collisionAction = $state<DuplicateResolutionAction | ''>('');
	let alternateRelativePath = $state('');
	let collisionError = $state('');

	const previewQuery = getLibraryManagementPreviewQuery(
		() => authStore.user?.id,
		() => jobId
	);
	const settingsQuery = getLibraryManagementSettingsQuery(
		() => authStore.user?.id,
		() => authStore.isAdmin
	);
	const policyQuery = getTargetLibrarySettingsQuery(() => authStore.isAdmin);
	const catalogSearchQuery = getLibrarySearchQuery(() => catalogSearch);
	const itemsQuery = getLibraryManagementPlanItemsQuery(
		() => authStore.user?.id,
		() => jobId,
		() => ({
			limit: 50,
			eligibility: eligibility || undefined,
			reasonCode: reasonCode || undefined,
			rootId: rootId || undefined,
			artistId: artistId || undefined,
			albumId: albumId || undefined,
			audioFormat: audioFormat || undefined,
			collisionClass: collisionClass || undefined,
			hasPreservedValue: hasPreservedValue || undefined,
			hasRepresentationLoss: hasRepresentationLoss || undefined,
			changeKind: changeKind || undefined
		})
	);
	const applyPreview = applyLibraryManagementPreviewMutation();
	const createResolution = createLibraryManagementDuplicateResolutionMutation();

	const preview = $derived(previewQuery.data ?? null);
	const items = $derived(itemsQuery.data?.pages.flatMap((page) => page.items) ?? []);
	const roots = $derived(policyQuery.data?.library_roots ?? []);
	const applyPhrase = 'APPLY LIBRARY MANAGEMENT';
	const canApply = $derived(
		Boolean(
			preview?.ready_for_confirmation &&
			!preview.stale &&
			!preview.expired &&
			preview.summary.eligible_count + preview.summary.warning_count > 0 &&
			previewToken
		)
	);
	const recycleAvailable = $derived(Boolean(settingsQuery.data?.recycle_bin_path.trim()));
	const providerStatus = $derived(
		preview?.summary.reasons.METADATA_UNAVAILABLE
			? 'Required metadata unavailable'
			: preview?.summary.reasons.OPTIONAL_ENRICHMENT_DEFERRED
				? 'Optional enrichment deferred'
				: 'Required metadata pinned'
	);
	const collisionRequestReady = $derived(
		Boolean(
			collisionSelection?.collision.requestKind &&
			collisionSelection.collision.existingRootId &&
			collisionSelection.collision.existingRelativePath &&
			collisionAction &&
			(!collisionAction.startsWith('recycle_') || recycleAvailable) &&
			(collisionAction !== 'keep_incoming_alternate' || alternateRelativePath.trim())
		)
	);

	onMount(() => {
		previewToken = readLibraryManagementPreviewToken(jobId);
		const events = createLibraryManagementEvents();
		events.start();
		return events.stop;
	});

	function rootLabel(value: string | null): string {
		return (
			roots.find((root) => root.id === value)?.label ?? (value ? 'Unavailable root' : 'No root')
		);
	}

	function displayPath(root: string | null, relative: string | null): string {
		return `${rootLabel(root)} · ${relative ?? 'No path'}`;
	}

	function desiredField(item: LibraryManagementPlanItem, name: string): string | null {
		const fields = item.desired_document.fields;
		if (!Array.isArray(fields)) return null;
		for (const value of fields) {
			if (isRecord(value) && value.name === name) return formatManagementValue(value.value);
		}
		return null;
	}

	function itemTitle(item: LibraryManagementPlanItem): string {
		return (
			desiredField(item, 'title') ??
			item.source_relative_path?.split('/').at(-1) ??
			`Item ${item.ordinal + 1}`
		);
	}

	function itemSubtitle(item: LibraryManagementPlanItem): string {
		const artist = desiredField(item, 'artist');
		const album = desiredField(item, 'album');
		return [artist, album].filter(Boolean).join(' · ') || `Album bundle ${item.bundle_ordinal + 1}`;
	}

	function formatBytes(value: number): string {
		if (value < 1024) return `${value} B`;
		if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
		if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
		return `${(value / 1024 ** 3).toFixed(1)} GiB`;
	}

	function formatDate(value: number | null): string {
		return value ? new Date(value * 1000).toLocaleString() : 'No expiry';
	}

	function chooseArtist(id: string, label: string): void {
		artistId = id;
		artistLabel = label;
		catalogSearch = '';
	}

	function chooseAlbum(id: string, label: string): void {
		albumId = id;
		albumLabel = label;
		catalogSearch = '';
	}

	function openApply(opener: HTMLButtonElement): void {
		applyOpener = opener;
		confirmation = '';
		applyError = '';
		applyDialog.showModal();
		applyHeading.focus();
	}

	async function apply(): Promise<void> {
		if (!preview || !previewToken || confirmation !== applyPhrase || !canApply) return;
		applyError = '';
		try {
			const operation = await applyPreview.mutateAsync({
				jobId,
				request: {
					preview_token: previewToken,
					expected_operation_row_revision: preview.operation_row_revision,
					idempotency_key: createUuid(),
					confirmation: true
				}
			});
			forgetLibraryManagementPreviewToken(jobId);
			applyDialog.close();
			await goto(`/library/management/operations/${encodeURIComponent(operation.id)}`);
		} catch (error) {
			applyError = error instanceof Error ? error.message : 'Could not apply this preview.';
		}
	}

	function openCollision(
		item: LibraryManagementPlanItem,
		collision: ManagementCollision,
		opener: HTMLButtonElement
	): void {
		collisionOpener = opener;
		collisionSelection = { item, collision };
		collisionAction = '';
		alternateRelativePath = '';
		collisionError = '';
		collisionDialog.showModal();
		collisionHeading.focus();
	}

	async function resolveCollision(): Promise<void> {
		const selection = collisionSelection;
		const settings = settingsQuery.data;
		const policy = policyQuery.data;
		if (
			!selection?.collision.requestKind ||
			!selection.collision.existingRootId ||
			!selection.collision.existingRelativePath ||
			!collisionAction ||
			!settings ||
			!policy ||
			!preview ||
			!collisionRequestReady
		) {
			return;
		}
		collisionError = '';
		try {
			const handle = await createResolution.mutateAsync({
				source_job_id: jobId,
				source_plan_item_ordinal: selection.item.ordinal,
				expected_source_operation_row_revision: preview.operation_row_revision,
				collision_kind: selection.collision.requestKind,
				existing_root_id: selection.collision.existingRootId,
				existing_relative_path: selection.collision.existingRelativePath,
				action: collisionAction,
				expected_settings_revision: settings.settings_revision,
				expected_policy_revision: policy.policy_revision,
				idempotency_key: createUuid(),
				existing_local_track_id: selection.collision.existingLocalTrackId,
				alternate_relative_path:
					collisionAction === 'keep_incoming_alternate' ? alternateRelativePath.trim() : null
			});
			rememberLibraryManagementPreviewToken(handle.job_id, handle.preview_token);
			collisionDialog.close();
			await goto(`/library/management/previews/${encodeURIComponent(handle.job_id)}`);
		} catch (error) {
			collisionError =
				error instanceof Error ? error.message : 'Could not create a resolution preview.';
		}
	}
</script>

<svelte:head><title>Library Management preview · DroppedNeedle</title></svelte:head>

<div class="management-preview-shell px-4 py-8 sm:px-6 lg:px-8">
	<main class="mx-auto max-w-7xl space-y-5">
		<a href="/library#operations" class="btn btn-ghost btn-sm -ml-2"
			><ArrowLeft class="h-4 w-4" /> Library control room</a
		>

		{#if previewQuery.isLoading || settingsQuery.isLoading || policyQuery.isLoading}
			<div class="space-y-4">
				<div class="skeleton h-40 rounded-2xl"></div>
				<div class="skeleton h-72 rounded-2xl"></div>
			</div>
		{:else if previewQuery.isError || settingsQuery.isError || policyQuery.isError}
			<div class="alert alert-error">Could not load this Library Management preview.</div>
		{:else if preview}
			<header class="management-control-room p-5 sm:p-7">
				<div class="flex flex-wrap items-start gap-4">
					<div class="management-write-mark"><FolderCog class="h-6 w-6" /></div>
					<div class="min-w-0 flex-1">
						<p class="management-kicker">
							<ShieldAlert class="h-3.5 w-3.5" /> Read-only plan · no files changed
						</p>
						<h1 class="mt-1 font-display text-2xl font-bold sm:text-3xl">
							{titleManagementValue(preview.mode)} preview
						</h1>
						<p class="mt-2 text-sm text-base-content/60">
							{preview.profile_name} · {titleManagementValue(preview.origin)} · created {formatDate(
								preview.created_at
							)}
						</p>
					</div>
					<span
						class="badge badge-lg {preview.ready_for_confirmation
							? 'badge-success'
							: 'badge-outline'}">{titleManagementValue(preview.phase)}</span
					>
				</div>
				<div class="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Eligible to write</span><strong
							>{preview.summary.eligible_count + preview.summary.warning_count}</strong
						><small>{preview.summary.warning_count} with warnings</small>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Blocked / unchanged</span><strong
							>{preview.summary.blocked_count} / {preview.summary.no_change_count}</strong
						><small>Never implicitly included</small>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Bundles / files</span><strong
							>{preview.summary.bundle_count} / {preview.summary.item_count}</strong
						><small>{preview.summary.expanded_track_count} tracks added by expansion</small>
					</div>
					<div class="management-summary-card">
						<span class="text-xs text-base-content/50">Temporary disk</span><strong
							>{formatBytes(preview.summary.estimated_temporary_bytes)}</strong
						><small>Required for staging and recovery</small>
					</div>
				</div>
				<div class="mt-3 flex flex-wrap gap-2 text-xs">
					<span class="badge badge-outline"
						><Tags class="h-3 w-3" /> {preview.summary.tag_change_count} tag changes</span
					>
					<span class="badge badge-outline"
						><Sparkles class="h-3 w-3" />
						{preview.summary.artwork_change_count} artwork changes</span
					>
					<span class="badge badge-outline"
						><FolderCog class="h-3 w-3" /> {preview.summary.path_change_count} path changes</span
					>
					<span class="badge badge-outline"
						><Layers3 class="h-3 w-3" />
						{preview.summary.sidecar_change_count} sidecar changes</span
					>
					<span class="badge badge-outline"
						><Clock3 class="h-3 w-3" /> Expires {formatDate(preview.expires_at)}</span
					>
					<span class="badge badge-outline"><HardDrive class="h-3 w-3" /> {providerStatus}</span>
				</div>
			</header>

			{#if preview.stale || preview.expired}
				<div class="alert alert-error items-start">
					<ShieldAlert class="mt-0.5 h-5 w-5" /><span
						><strong>This preview cannot be applied.</strong><br />{preview.expired
							? 'It expired. Generate a fresh preview.'
							: preview.stale_reasons.map(titleManagementValue).join(' · ')}</span
					>
				</div>
			{:else if preview.state !== 'ready'}
				<div class="alert alert-info">
					<span class="loading loading-spinner loading-sm"></span><span
						>Planning is still read-only. {preview.completed_count.toLocaleString()} of {preview.expected_work_count.toLocaleString()}
						items inspected.</span
					>
				</div>
			{/if}

			<section class="management-operation-panel space-y-4" aria-labelledby="preview-filters-title">
				<div class="flex flex-wrap items-end justify-between gap-2">
					<div>
						<p class="management-step">Inspectable plan</p>
						<h2 id="preview-filters-title" class="font-display text-xl font-semibold">
							Files and changes
						</h2>
					</div>
					<span class="text-xs text-base-content/45">Root labels and relative paths only</span>
				</div>
				<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
					<label class="grid gap-1 text-xs"
						><span>Outcome</span><select
							class="select select-bordered select-sm bg-base-100"
							bind:value={eligibility}
							><option value="">All outcomes</option><option value="eligible">Eligible</option
							><option value="warning">Warning</option><option value="blocked">Blocked</option
							><option value="stale">Stale</option></select
						></label
					>
					<label class="grid gap-1 text-xs"
						><span>Reason</span><select
							class="select select-bordered select-sm bg-base-100"
							bind:value={reasonCode}
							><option value="">All reasons</option
							>{#each Object.keys(preview.summary.reasons) as reason (reason)}<option value={reason}
									>{titleManagementValue(reason)}</option
								>{/each}</select
						></label
					>
					<label class="grid gap-1 text-xs"
						><span>Root</span><select
							class="select select-bordered select-sm bg-base-100"
							bind:value={rootId}
							><option value="">All roots</option
							>{#each Object.keys(preview.summary.roots) as root (root)}<option value={root}
									>{rootLabel(root)}</option
								>{/each}</select
						></label
					>
					<label class="grid gap-1 text-xs"
						><span>Format</span><select
							class="select select-bordered select-sm bg-base-100"
							bind:value={audioFormat}
							><option value="">All formats</option
							>{#each Object.keys(preview.summary.formats) as format (format)}<option value={format}
									>{format.toUpperCase()}</option
								>{/each}</select
						></label
					>
					<label class="grid gap-1 text-xs"
						><span>Change</span><select
							class="select select-bordered select-sm bg-base-100"
							bind:value={changeKind}
							><option value="">All changes</option><option value="tags">Tags</option><option
								value="artwork">Artwork</option
							><option value="path">Path</option><option value="sidecars">Sidecars</option><option
								value="no_change">No change</option
							></select
						></label
					>
				</div>
				<details class="rounded-xl border border-base-content/10 bg-base-200/35 p-3">
					<summary class="cursor-pointer text-sm font-semibold"
						>Artist, album, collision, and preservation filters</summary
					>
					<div class="mt-3 grid gap-3 lg:grid-cols-2">
						<div class="space-y-2">
							<label class="grid gap-1 text-xs"
								><span>Find an artist or album</span><input
									class="input input-bordered input-sm bg-base-100"
									bind:value={catalogSearch}
									placeholder="Type at least two characters"
								/></label
							>
							{#if artistId || albumId}<div class="flex flex-wrap gap-1">
									{#if artistId}<button
											class="badge badge-outline gap-1"
											onclick={() => {
												artistId = '';
												artistLabel = '';
											}}>Artist: {artistLabel} ×</button
										>{/if}{#if albumId}<button
											class="badge badge-outline gap-1"
											onclick={() => {
												albumId = '';
												albumLabel = '';
											}}>Album: {albumLabel} ×</button
										>{/if}
								</div>{/if}
							{#if catalogSearch.trim().length >= 2 && catalogSearchQuery.data}<div
									class="grid max-h-44 gap-1 overflow-y-auto rounded-xl border border-base-content/10 bg-base-100 p-2"
								>
									{#each catalogSearchQuery.data.artists as artist (artist.id)}<button
											class="btn btn-ghost btn-sm justify-start"
											onclick={() => chooseArtist(artist.id, artist.name)}
											>Artist · {artist.name}</button
										>{/each}{#each catalogSearchQuery.data.albums as album (album.id)}<button
											class="btn btn-ghost btn-sm justify-start"
											onclick={() => chooseAlbum(album.id, `${album.artist_name} · ${album.title}`)}
											>Album · {album.artist_name} · {album.title}</button
										>{/each}
								</div>{/if}
						</div>
						<div class="grid gap-2 sm:grid-cols-2">
							<label class="grid gap-1 text-xs sm:col-span-2"
								><span>Collision class</span><select
									class="select select-bordered select-sm bg-base-100"
									bind:value={collisionClass}
									><option value="">All collision classes</option
									>{#each ['same_path_same_content', 'same_path_different_content', 'same_release_position_different_content', 'normalized_path_collision', 'normalized_catalog_path_collision', 'sidecar_path_collision', 'destination_created_after_preview'] as option (option)}<option
											value={option}>{titleManagementValue(option)}</option
										>{/each}</select
								></label
							>
							<label class="management-trigger"
								><input
									type="checkbox"
									class="checkbox checkbox-sm"
									bind:checked={hasPreservedValue}
								/><span
									><strong>Preserved / local override</strong><small
										>Values intentionally left unchanged</small
									></span
								></label
							>
							<label class="management-trigger"
								><input
									type="checkbox"
									class="checkbox checkbox-sm"
									bind:checked={hasRepresentationLoss}
								/><span
									><strong>Lossy representation</strong><small
										>Format cannot store the exact value shape</small
									></span
								></label
							>
						</div>
					</div>
				</details>
			</section>

			{#if itemsQuery.isLoading}
				<div class="space-y-3">
					<div class="skeleton h-28 rounded-xl"></div>
					<div class="skeleton h-28 rounded-xl"></div>
				</div>
			{:else if itemsQuery.isError}
				<div class="alert alert-error">Could not load preview items.</div>
			{:else if items.length === 0}
				<div
					class="rounded-2xl border border-dashed border-base-content/15 p-8 text-center text-base-content/50"
				>
					No files match these filters.
				</div>
			{:else}
				<div class="space-y-3">
					{#each items as item (item.ordinal)}
						{@const diffs = [...managementFieldDiffs(item), ...managementCustomTagDiffs(item)]}
						{@const warnings = managementStringList(item.capability.warnings)}
						{@const blockers = managementStringList(item.capability.blockers)}
						{@const losses = managementStringList(item.capability.representation_losses)}
						{@const sidecars = managementSidecars(item)}
						{@const collisions = managementCollisions(item)}
						<article class="management-preview-item" data-eligibility={item.eligibility}>
							<div class="flex flex-wrap items-start gap-3 p-4">
								<div class="min-w-0 flex-1">
									<div class="flex flex-wrap items-center gap-2">
										<span
											class="badge badge-sm {item.eligibility === 'eligible'
												? 'badge-success'
												: item.eligibility === 'warning'
													? 'badge-warning'
													: 'badge-error'}">{titleManagementValue(item.eligibility)}</span
										><span class="font-mono text-[0.65rem] text-base-content/40"
											>Bundle {item.bundle_ordinal + 1} · {managementAudioFormat(
												item
											).toUpperCase()}</span
										>
									</div>
									<h3 class="mt-2 truncate font-semibold">{itemTitle(item)}</h3>
									<p class="truncate text-sm text-base-content/55">{itemSubtitle(item)}</p>
									{#if item.reason_code}<p class="mt-1 text-xs font-semibold text-error">
											{titleManagementValue(item.reason_code)}
										</p>{/if}
								</div>
								<div class="text-right text-xs text-base-content/50">
									<p>{displayPath(item.source_root_id, item.source_relative_path)}</p>
									{#if item.destination_relative_path && (item.destination_root_id !== item.source_root_id || item.destination_relative_path !== item.source_relative_path)}<p
											class="mt-1 text-base-content/75"
										>
											→ {displayPath(item.destination_root_id, item.destination_relative_path)}
										</p>{/if}
								</div>
							</div>
							<details class="border-t border-base-content/10">
								<summary
									class="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-semibold"
									><ChevronRight class="h-4 w-4" /> Inspect exact diff</summary
								>
								<div class="space-y-4 px-4 pb-4">
									{#if diffs.length}<section>
											<h4
												class="mb-2 text-xs font-bold uppercase tracking-wider text-base-content/50"
											>
												Metadata
											</h4>
											{#each diffs as diff (`${diff.name}:${diff.operation}`)}<div
													class="management-diff-row"
												>
													<strong class="text-sm">{titleManagementValue(diff.name)}</strong><span
														class="management-diff-value"
														data-side="before">{formatManagementValue(diff.before)}</span
													><span
														class="management-diff-badge text-xs font-bold uppercase"
														data-operation={diff.operation}
														>{titleManagementValue(diff.operation)}
														<ArrowRight class="inline h-3 w-3" /></span
													><span class="management-diff-value" data-side="after"
														>{formatManagementValue(diff.after)}</span
													>{#if diff.representationLoss}<small class="text-warning sm:col-span-4"
															>Format representation: {diff.representationLoss}</small
														>{/if}
												</div>{/each}
										</section>{/if}
									{#if item.source_relative_path !== item.destination_relative_path || item.source_root_id !== item.destination_root_id}<section
										>
											<h4
												class="mb-2 text-xs font-bold uppercase tracking-wider text-base-content/50"
											>
												Organization
											</h4>
											<div class="grid gap-2 sm:grid-cols-[1fr_auto_1fr]">
												<code class="management-diff-value" data-side="before"
													>{displayPath(item.source_root_id, item.source_relative_path)}</code
												><ArrowRight class="mt-2 h-4 w-4" /><code
													class="management-diff-value"
													data-side="after"
													>{displayPath(
														item.destination_root_id,
														item.destination_relative_path
													)}</code
												>
											</div>
										</section>{/if}
									{#if warnings.length || blockers.length || losses.length}<section
											class="grid gap-2 sm:grid-cols-3"
										>
											<div>
												<h4 class="text-xs font-bold uppercase text-base-content/50">Adapter</h4>
												<p class="text-sm">
													{managementAdapter(item) ?? 'No writer adapter'} · {managementAudioFormat(
														item
													).toUpperCase()}
												</p>
											</div>
											<div>
												<h4 class="text-xs font-bold uppercase text-base-content/50">Warnings</h4>
												<p class="text-sm">
													{[...warnings, ...losses].map(titleManagementValue).join(' · ') || 'None'}
												</p>
											</div>
											<div>
												<h4 class="text-xs font-bold uppercase text-base-content/50">Blockers</h4>
												<p class="text-sm">
													{blockers.map(titleManagementValue).join(' · ') || 'None'}
												</p>
											</div>
										</section>{/if}
									{#if sidecars.length}<section>
											<h4 class="text-xs font-bold uppercase text-base-content/50">Sidecars</h4>
											<ul class="mt-1 space-y-1 text-sm">
												{#each sidecars as sidecar, index (index)}<li>
														{formatManagementValue(sidecar)}
													</li>{/each}
											</ul>
										</section>{/if}
									{#if item.artwork_choices.length}<section>
											<h4 class="text-xs font-bold uppercase text-base-content/50">Artwork</h4>
											<p class="text-sm">
												{item.artwork_choices.length} pinned artwork output{item.artwork_choices
													.length === 1
													? ''
													: 's'}; source and sizing decisions are preserved in this preview.
											</p>
										</section>{/if}
									{#if collisions.length}
										<section class="space-y-2">
											<h4 class="text-xs font-bold uppercase text-error">Collision evidence</h4>
											{#each collisions as collision, index (index)}
												<div
													class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-error/25 bg-error/5 p-3"
												>
													<div>
														<strong class="text-sm"
															>{titleManagementValue(collision.classification)}</strong
														>
														<p class="text-xs text-base-content/55">
															No file is assumed safe to delete. Both sides are revalidated in a new
															preview.
														</p>
													</div>
													{#if collision.requestKind && collision.existingRootId && collision.existingRelativePath}
														<button
															class="btn btn-outline btn-sm"
															onclick={(event) =>
																openCollision(item, collision, event.currentTarget)}
															>Choose resolution...</button
														>
													{:else}
														<span class="badge badge-error badge-outline"
															>Requires fresh scan evidence</span
														>
													{/if}
												</div>
											{/each}
										</section>
									{/if}
								</div>
							</details>
						</article>
					{/each}
				</div>
				{#if itemsQuery.hasNextPage}<button
						class="btn btn-outline w-full"
						disabled={itemsQuery.isFetchingNextPage}
						onclick={() => void itemsQuery.fetchNextPage()}
						>{#if itemsQuery.isFetchingNextPage}<span class="loading loading-spinner loading-sm"
							></span>{/if} Load more files</button
					>{/if}
			{/if}

			<div class="management-apply-bar">
				<div class="flex items-start gap-2">
					<ShieldAlert class="mt-0.5 h-5 w-5 text-library-manage" />
					<div>
						<strong>Applying is the first write action</strong>
						<p class="text-xs text-base-content/55">
							Blocked, stale, and no-change rows are excluded.
						</p>
						{#if !previewToken && preview.ready_for_confirmation}<p
								class="mt-1 text-xs text-warning"
							>
								The private apply token is not in this browser session. Generate a fresh preview to
								apply.
							</p>{/if}
					</div>
				</div>
				<button
					class="btn management-btn"
					disabled={!canApply}
					onclick={(event) => openApply(event.currentTarget)}
					>Write tags and organize {preview.summary.eligible_count + preview.summary.warning_count} files</button
				>
			</div>
		{/if}
	</main>
</div>

<dialog
	bind:this={applyDialog}
	class="modal"
	aria-labelledby="apply-management-title"
	onclose={() => applyOpener?.focus()}
	oncancel={(event) => {
		if (applyPreview.isPending) event.preventDefault();
	}}
>
	<div class="modal-box max-w-lg border border-warning/30">
		<div class="flex items-start gap-3">
			<div class="management-write-mark"><ShieldAlert class="h-5 w-5" /></div>
			<div>
				<p class="management-kicker">Write confirmation</p>
				<h2
					bind:this={applyHeading}
					id="apply-management-title"
					tabindex="-1"
					class="font-display text-xl font-semibold"
				>
					Apply this exact preview?
				</h2>
			</div>
		</div>
		<p class="mt-4 text-sm text-base-content/65">
			DroppedNeedle will write tags and organize {preview?.summary.eligible_count ?? 0} eligible files
			plus {preview?.summary.warning_count ?? 0} files with warnings. No destination is overwritten automatically.
		</p>
		<label class="mt-4 grid gap-1 text-sm"
			><span>Type <strong>{applyPhrase}</strong></span><input
				class="input input-bordered bg-base-100 font-mono"
				bind:value={confirmation}
				autocomplete="off"
			/></label
		>
		{#if applyError}<div class="alert alert-error mt-3 text-sm" role="alert">{applyError}</div>{/if}
		<div class="modal-action">
			<button
				class="btn btn-ghost"
				disabled={applyPreview.isPending}
				onclick={() => applyDialog.close()}>Cancel</button
			><button
				class="btn btn-warning"
				disabled={!canApply || confirmation !== applyPhrase || applyPreview.isPending}
				onclick={() => void apply()}
				>{#if applyPreview.isPending}<span class="loading loading-spinner loading-sm"
					></span>{/if}<CheckCircle2 class="h-4 w-4" /> Apply exact preview</button
			>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button aria-label="Cancel applying management preview" disabled={applyPreview.isPending}
			>close</button
		>
	</form>
</dialog>

<dialog
	bind:this={collisionDialog}
	class="modal"
	aria-labelledby="resolve-management-collision"
	onclose={() => collisionOpener?.focus()}
	oncancel={(event) => {
		if (createResolution.isPending) event.preventDefault();
	}}
>
	<div class="modal-box max-w-2xl border border-error/25">
		<div class="flex items-start justify-between gap-3">
			<div>
				<p class="management-kicker">Fresh preview required</p>
				<h2
					bind:this={collisionHeading}
					id="resolve-management-collision"
					tabindex="-1"
					class="font-display text-xl font-semibold"
				>
					Choose a collision resolution
				</h2>
				<p class="mt-1 text-sm text-base-content/55">
					No option is preselected. DroppedNeedle rechecks both files before it offers another Apply
					action.
				</p>
			</div>
			<button
				class="btn btn-ghost btn-sm btn-square"
				aria-label="Close collision resolution"
				disabled={createResolution.isPending}
				onclick={() => collisionDialog.close()}><X class="h-5 w-5" /></button
			>
		</div>
		{#if collisionSelection}<div class="mt-4 rounded-xl border border-base-content/10 p-3 text-sm">
				<p>
					<strong>Incoming:</strong>
					{displayPath(
						collisionSelection.item.source_root_id,
						collisionSelection.item.source_relative_path
					)}
				</p>
				<p class="mt-1">
					<strong>Existing:</strong>
					{displayPath(
						collisionSelection.collision.existingRootId,
						collisionSelection.collision.existingRelativePath
					)}
				</p>
				<p class="mt-1">
					<strong>Evidence:</strong>
					{titleManagementValue(collisionSelection.collision.classification)}
				</p>
			</div>{/if}
		<fieldset class="mt-4 grid gap-2">
			<legend class="mb-2 text-sm font-semibold">Resolution</legend>
			<label class="management-selection-card"
				><input
					type="radio"
					class="radio radio-sm"
					name="collision-action"
					value="keep_existing"
					bind:group={collisionAction}
				/><span
					><strong>Keep existing; leave incoming in place</strong><small
						>Creates a no-write resolution preview for the incoming destination.</small
					></span
				></label
			>
			<label class="management-selection-card"
				><input
					type="radio"
					class="radio radio-sm"
					name="collision-action"
					value="keep_incoming_alternate"
					bind:group={collisionAction}
				/><span
					><strong>Keep incoming at an alternate relative path</strong><small
						>Both files remain.</small
					></span
				></label
			>
			<label class="management-selection-card"
				><input
					type="radio"
					class="radio radio-sm"
					name="collision-action"
					value="recycle_existing_keep_incoming"
					bind:group={collisionAction}
					disabled={!recycleAvailable}
				/><span
					><strong>Recycle existing; keep incoming</strong><small
						>{recycleAvailable
							? 'Moves the existing file to the configured recycle area.'
							: 'Unavailable until a recycle directory is configured.'}</small
					></span
				></label
			>
			<label class="management-selection-card"
				><input
					type="radio"
					class="radio radio-sm"
					name="collision-action"
					value="recycle_incoming_keep_existing"
					bind:group={collisionAction}
					disabled={!recycleAvailable}
				/><span
					><strong>Recycle incoming; keep existing</strong><small
						>{recycleAvailable
							? 'Moves the incoming file to the configured recycle area.'
							: 'Unavailable until a recycle directory is configured.'}</small
					></span
				></label
			>
		</fieldset>
		{#if collisionAction === 'keep_incoming_alternate'}<label class="mt-3 grid gap-1 text-sm"
				><span>Alternate relative path</span><input
					class="input input-bordered bg-base-100 font-mono"
					bind:value={alternateRelativePath}
					placeholder="Artist/Album/02 Track (alternate).flac"
				/><small class="text-base-content/45"
					>Relative to the planned destination root; absolute paths are rejected.</small
				></label
			>{/if}
		{#if collisionError}<div class="alert alert-error mt-3 text-sm" role="alert">
				{collisionError}
			</div>{/if}
		<div class="modal-action">
			<button
				class="btn btn-ghost"
				disabled={createResolution.isPending}
				onclick={() => collisionDialog.close()}>Cancel</button
			><button
				class="btn management-btn"
				disabled={!collisionRequestReady || createResolution.isPending}
				onclick={() => void resolveCollision()}
				>{#if createResolution.isPending}<span class="loading loading-spinner loading-sm"
					></span>{/if}<HardDrive class="h-4 w-4" /> Generate resolution preview</button
			>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button aria-label="Cancel collision resolution" disabled={createResolution.isPending}
			>close</button
		>
	</form>
</dialog>
