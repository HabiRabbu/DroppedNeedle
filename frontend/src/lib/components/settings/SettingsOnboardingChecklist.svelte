<script lang="ts">
	import { Circle, CircleCheck } from 'lucide-svelte';

	import {
		getDownloadClientConfigQuery,
		getDownloadClientStatusQuery
	} from '$lib/queries/downloads/DownloadClientQueries.svelte';
	import { getSabnzbdConfigQuery } from '$lib/queries/downloads/DownloadClientsQueries.svelte';
	import { getIndexersQuery } from '$lib/queries/downloads/IndexerQueries.svelte';
	import { getTargetLibrarySettingsQuery } from '$lib/queries/library/LibraryPolicyQueries.svelte';

	const libQuery = getTargetLibrarySettingsQuery();
	const dcQuery = getDownloadClientConfigQuery();
	const statusQuery = getDownloadClientStatusQuery();
	const sabQuery = getSabnzbdConfigQuery();
	const indexersQuery = getIndexersQuery();

	const hasLibraryPath = $derived((libQuery.data?.library_roots.length ?? 0) > 0);
	const slskdConfigured = $derived(Boolean(dcQuery.data?.url && dcQuery.data?.api_key));
	const sabnzbdEnabled = $derived(sabQuery.data?.enabled === true && Boolean(sabQuery.data?.url));
	const hasIndexer = $derived((indexersQuery.data?.length ?? 0) > 0);
	const mountOk = $derived(statusQuery.data?.mount?.ok === true);
	const hasAcoustid = $derived(Boolean(libQuery.data?.acoustid_api_key));

	// Source-agnostic: "configured" if EITHER acquisition path can act, so a Usenet-only
	// (or Soulseek-only) install isn't nagged about the other. The slskd mount item only
	// appears once Soulseek is set up.
	const aSourceConfigured = $derived(slskdConfigured || hasIndexer);
	const aClientConfigured = $derived(slskdConfigured || sabnzbdEnabled);

	const items = $derived([
		{ label: 'Add a library path', done: hasLibraryPath, required: true, optional: false },
		{
			label: 'Add an indexer or configure Soulseek',
			done: aSourceConfigured,
			required: true,
			optional: false
		},
		{
			label: 'Configure a download client (slskd and/or SABnzbd)',
			done: aClientConfigured,
			required: true,
			optional: false
		},
		...(slskdConfigured
			? [
					{
						label: "Mount slskd's downloads folder",
						done: mountOk,
						required: true,
						optional: false
					}
				]
			: []),
		...(sabnzbdEnabled
			? [{ label: "Mount SABnzbd's downloads folder", done: true, required: false, optional: true }]
			: []),
		{ label: 'Run a library scan', done: false, required: false, optional: true },
		{ label: 'Set an AcoustID key', done: hasAcoustid, required: false, optional: true }
	]);

	const doneCount = $derived(items.filter((i) => i.done).length);
	const requiredDone = $derived(items.filter((i) => i.required).every((i) => i.done));

	// collapse once required items are done; manual toggle overrides
	let manualToggle = $state<boolean | null>(null);
	const expanded = $derived(manualToggle ?? !requiredDone);
</script>

<div class="card border border-base-300 bg-base-200">
	<button
		type="button"
		class="flex w-full items-center justify-between px-6 py-4 text-left"
		onclick={() => (manualToggle = !expanded)}
		aria-expanded={expanded}
	>
		<div>
			<h3 class="font-semibold">Setup checklist</h3>
			<p class="text-sm text-base-content/60">{doneCount}/{items.length} complete</p>
		</div>
		<span class="text-sm text-base-content/60">{expanded ? 'Hide' : 'Show'}</span>
	</button>
	{#if expanded}
		<ul class="space-y-2 px-6 pb-5">
			{#each items as item (item.label)}
				<li class="flex items-center gap-2 text-sm">
					{#if item.done}
						<CircleCheck class="size-4 shrink-0 text-success" aria-hidden="true" />
					{:else}
						<Circle class="size-4 shrink-0 text-base-content/30" aria-hidden="true" />
					{/if}
					<span class={item.optional && !item.done ? 'text-base-content/50' : ''}>{item.label}</span
					>
					{#if item.optional}<span class="badge badge-ghost badge-xs">optional</span>{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>
