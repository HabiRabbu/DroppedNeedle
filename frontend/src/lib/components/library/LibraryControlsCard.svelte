<script lang="ts">
	import { Radar, ArrowRight, CalendarClock, Play } from 'lucide-svelte';
	import {
		getLibrarySettingsQuery,
		getLibraryScanScheduleQuery
	} from '$lib/queries/library/LibraryQueries.svelte';
	import LibraryScanScheduleControl from './LibraryScanScheduleControl.svelte';
	import LibraryScanButton from './LibraryScanButton.svelte';
	import LibraryForceRescanButton from './LibraryForceRescanButton.svelte';
	import { scanFrequencyLabel } from '$lib/utils/scanFrequency';
	import { formatLastUpdated } from '$lib/utils/formatting';
	import { authStore } from '$lib/stores/authStore.svelte';

	interface Props {
		lastScan?: Date | null;
	}
	let { lastScan = null }: Props = $props();

	const settingsQuery = getLibrarySettingsQuery(() => authStore.isAdmin);
	const scheduleQuery = getLibraryScanScheduleQuery(() => authStore.isAdmin);

	const paths = $derived(settingsQuery.data?.library_paths ?? []);
	const hasPath = $derived(paths.length > 0);
	const hasKey = $derived(!!settingsQuery.data?.acoustid_api_key);
	const isManual = $derived(scheduleQuery.data?.scan_frequency === 'manual');
	const freqLabel = $derived(
		scheduleQuery.data?.scan_frequency === 'daily'
			? `Daily at ${scheduleQuery.data?.daily_scan_time ?? '03:00'}`
			: scanFrequencyLabel(scheduleQuery.data?.scan_frequency)
	);
</script>

<div class="overflow-hidden rounded-box border border-base-300 bg-base-200">
	<div class="flex flex-wrap items-center gap-3 border-b border-base-300 px-4 py-3.5">
		<div
			class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 ring-1 ring-primary/30"
		>
			<Radar class="h-5 w-5 text-primary" />
		</div>
		<div class="min-w-0 flex-1">
			<div class="font-semibold">Library controls</div>
			<div class="text-sm text-base-content/60">
				{isManual ? 'Auto-scan off' : `Auto-scan · ${freqLabel}`}
			</div>
		</div>
		<span class="text-sm text-base-content/60">
			Last scan {lastScan ? formatLastUpdated(lastScan) : 'never'}
		</span>
	</div>

	<div class="grid gap-5 p-4 sm:grid-cols-2 sm:gap-6">
		<section class="space-y-2.5">
			<h3 class="flex items-center gap-1.5 text-sm font-semibold">
				<CalendarClock class="h-4 w-4 text-base-content/50" /> Automatic scanning
			</h3>
			<LibraryScanScheduleControl />
		</section>

		<section class="space-y-2.5">
			<h3 class="flex items-center gap-1.5 text-sm font-semibold">
				<Play class="h-4 w-4 text-base-content/50" /> Manual scan
			</h3>
			<div class="flex flex-wrap items-center gap-2">
				<LibraryScanButton {hasPath} disabled={!hasPath} class="btn btn-primary btn-sm gap-1" />
				<LibraryForceRescanButton {hasPath} class="btn btn-outline btn-error btn-sm gap-1" />
			</div>
			{#if !hasPath}
				<p class="text-xs text-base-content/50">
					Add a library path in settings to enable scanning.
				</p>
			{/if}
		</section>
	</div>

	<div
		class="flex flex-wrap items-center justify-between gap-2 border-t border-base-300 px-4 py-3 text-xs text-base-content/60"
	>
		<span class="truncate">
			{paths.length} path{paths.length === 1 ? '' : 's'} · AcoustID {hasKey ? 'set' : 'not set'}
		</span>
		<a class="link link-hover inline-flex items-center gap-1" href="/settings?tab=library">
			Manage library settings <ArrowRight class="h-3.5 w-3.5" />
		</a>
	</div>
</div>
