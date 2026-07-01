<script lang="ts">
	import {
		CircleCheck,
		CircleX,
		FolderTree,
		HardDriveDownload,
		Info,
		TriangleAlert
	} from 'lucide-svelte';

	import {
		getDownloadClientConfigQuery,
		getDownloadClientStatusQuery,
		saveDownloadClientConfig,
		testDownloadClient
	} from '$lib/queries/downloads/DownloadClientQueries.svelte';
	import { toastStore } from '$lib/stores/toast';
	import type { DownloadClientConfig, TestConnectionResult } from '$lib/types';

	import DownloadClientCard from './DownloadClientCard.svelte';

	const configQuery = getDownloadClientConfigQuery();
	const statusQuery = getDownloadClientStatusQuery();
	const save = saveDownloadClientConfig();
	const test = testDownloadClient();

	let enabled = $state(false);
	let url = $state('');
	let apiKey = $state('');
	let showKey = $state(false);
	let downloadsSubpath = $state('');
	// Quality/verification/resilience now live in the shared Download policy block, but the
	// slskd config struct still carries them, so seed + round-trip them on save to avoid
	// resetting the stored values (the orchestrator reads them from download_policy).
	let policyFields = $state<Partial<DownloadClientConfig>>({});
	let seeded = $state(false);
	let testResult = $state<TestConnectionResult | null>(null);

	$effect(() => {
		const d = configQuery.data;
		if (d && !seeded) {
			enabled = d.enabled;
			url = d.url;
			apiKey = d.api_key;
			downloadsSubpath = d.downloads_subpath ?? '';
			policyFields = {
				verify_downloads: d.verify_downloads,
				quality_min: d.quality_min,
				quality_max: d.quality_max,
				flac_mp3_only: d.flac_mp3_only,
				preflight_score_auto_accept: d.preflight_score_auto_accept,
				preflight_score_manual_min: d.preflight_score_manual_min,
				download_stall_timeout_minutes: d.download_stall_timeout_minutes,
				download_queued_timeout_minutes: d.download_queued_timeout_minutes,
				max_failover_attempts: d.max_failover_attempts,
				max_concurrent_downloads: d.max_concurrent_downloads
			};
			seeded = true;
		}
	});

	const status = $derived(statusQuery.data);
	const connected = $derived(status?.configured === true && status?.client.status === 'ok');
	const statusText = $derived(
		connected
			? `Connected${status?.client.version ? ` · v${status.client.version}` : ''}`
			: status?.configured
				? (status?.client.message ?? 'Not reachable')
				: 'Not configured'
	);
	const mount = $derived(status?.mount);
	const mountAdvisory = $derived(status?.mount_advisory);
	const slskdDownloadsDir = $derived(status?.slskd_downloads_dir);

	const MOUNT_REASONS: Record<string, string> = {
		not_set: 'No slskd downloads folder is mounted into DroppedNeedle.',
		missing: "The mounted downloads folder doesn't exist.",
		not_writable: 'The downloads mount is read-only - imports MOVE files, so it must be writable.'
	};

	function currentConfig(): DownloadClientConfig | null {
		const d = configQuery.data;
		if (!d) return null;
		return {
			...d,
			...policyFields,
			enabled,
			url,
			api_key: apiKey,
			downloads_subpath: downloadsSubpath
		};
	}

	async function handleTest() {
		testResult = null;
		const config = currentConfig();
		if (!config) return;
		try {
			testResult = await test.mutateAsync(config);
		} catch (e) {
			testResult = { valid: false, message: e instanceof Error ? e.message : 'Connection failed' };
		}
	}

	async function handleSave() {
		const config = currentConfig();
		if (!config) return;
		try {
			await save.mutateAsync(config);
			toastStore.show({ message: 'Soulseek settings saved', type: 'success' });
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to save download client',
				type: 'error'
			});
		}
	}

	// The enable switch persists immediately (it lives in the collapsed header, so users
	// shouldn't have to expand + Save just to flip a source on/off). Revert on failure.
	async function handleToggle() {
		const config = currentConfig();
		if (!config) return;
		try {
			await save.mutateAsync(config);
			toastStore.show({ message: `Soulseek ${enabled ? 'enabled' : 'disabled'}`, type: 'success' });
		} catch {
			enabled = !enabled;
			toastStore.show({ message: 'Could not update Soulseek', type: 'error' });
		}
	}
</script>

{#if configQuery.isLoading}
	<div class="skeleton h-28 w-full rounded-box"></div>
{:else if configQuery.isError}
	<div class="alert alert-error">
		Failed to load Soulseek settings: {configQuery.error.message}
	</div>
{:else}
	<DownloadClientCard
		title="slskd"
		sourceLabel="Soulseek"
		icon={HardDriveDownload}
		{connected}
		{statusText}
		bind:enabled
		onToggle={handleToggle}
		enableAriaLabel="Enable slskd download client"
	>
		<section class="space-y-3">
			<div class="form-control">
				<label class="label" for="slskd-url"><span class="label-text">slskd URL</span></label>
				<input
					id="slskd-url"
					class="input input-bordered w-full font-mono text-sm"
					bind:value={url}
					placeholder="http://slskd:5030"
				/>
			</div>
			<div class="form-control">
				<label class="label" for="slskd-key"><span class="label-text">API key</span></label>
				<div class="join w-full">
					<input
						id="slskd-key"
						type={showKey ? 'text' : 'password'}
						class="input input-bordered join-item flex-1 font-mono text-sm"
						bind:value={apiKey}
						placeholder="slskd API key"
					/>
					<button
						type="button"
						class="btn join-item"
						onclick={() => (showKey = !showKey)}
						aria-label={showKey ? 'Hide API key' : 'Show API key'}
					>
						{showKey ? 'Hide' : 'Show'}
					</button>
				</div>
			</div>
			<div class="flex flex-wrap items-center gap-3">
				<button
					type="button"
					class="btn btn-outline btn-sm"
					onclick={handleTest}
					disabled={test.isPending || !url}
				>
					{#if test.isPending}<span class="loading loading-spinner loading-xs"></span>{/if}
					Test connection
				</button>
				{#if testResult}
					<span
						class="flex items-center gap-1.5 text-sm"
						class:text-success={testResult.valid}
						class:text-error={!testResult.valid}
					>
						{#if testResult.valid}
							<CircleCheck class="size-4" aria-hidden="true" /> Connected{testResult.version
								? ` · v${testResult.version}`
								: ''}
						{:else}
							<CircleX class="size-4" aria-hidden="true" /> {testResult.message}
						{/if}
					</span>
				{/if}
			</div>
		</section>

		<p class="text-xs leading-relaxed text-base-content/60">
			DroppedNeedle only orchestrates your own slskd instance over its local HTTP API; it never
			joins or distributes on the Soulseek network. You supply, run, and are responsible for slskd
			and its shared folders.
		</p>

		<div class="alert alert-warning items-start text-sm">
			<TriangleAlert class="size-5 shrink-0" aria-hidden="true" />
			<span>
				<span class="font-semibold">Share files in slskd.</span> Soulseek bans leechers - configure
				shared directories in <code>slskd.yml</code> so you can keep downloading.
			</span>
		</div>

		<section class="space-y-2">
			<div class="flex items-center gap-2 text-sm font-semibold">
				<FolderTree class="size-4 text-base-content/70" aria-hidden="true" /> Downloads mount
			</div>
			{#if mount?.ok && mountAdvisory}
				<div class="alert alert-warning items-start text-sm">
					<TriangleAlert class="size-5 shrink-0" aria-hidden="true" />
					<div class="space-y-1">
						<p>{mountAdvisory}</p>
						{#if mount.path}<code class="text-base-content/60">{mount.path}</code>{/if}
					</div>
				</div>
				<div class="space-y-1.5 rounded-box border border-base-content/10 bg-base-200/40 p-3">
					<label class="text-sm font-medium" for="downloads-subpath">Downloads subfolder</label>
					<p class="text-xs text-base-content/60">
						The folder inside your mount where slskd saves completed downloads.
						{#if slskdDownloadsDir}
							slskd saves to <code class="text-base-content/70">{slskdDownloadsDir}</code>. Set this
							to the part of that path inside your mount.
						{/if}
					</p>
					<div class="flex flex-wrap items-center gap-2">
						<input
							id="downloads-subpath"
							type="text"
							class="input input-sm input-bordered flex-1 font-mono"
							placeholder="e.g. downloads/slskd/complete"
							bind:value={downloadsSubpath}
						/>
						<button class="btn btn-sm btn-primary" onclick={handleSave} disabled={save.isPending}>
							{save.isPending ? 'Checking…' : 'Save & re-check'}
						</button>
					</div>
				</div>
			{:else if mount?.ok}
				<div class="flex items-center gap-2 text-sm text-success">
					<CircleCheck class="size-4" aria-hidden="true" />
					Reachable on the same disk as your library
					{#if mount.path}<code class="text-base-content/60">{mount.path}</code>{/if}
				</div>
			{:else if mount?.reason === 'different_filesystem'}
				<div class="alert alert-info items-start text-sm">
					<Info class="size-5 shrink-0" aria-hidden="true" />
					<div class="space-y-1">
						<p>
							Your downloads and library are on different filesystems. Imports still work -
							DroppedNeedle copies each file into the library instead of moving it instantly, so
							it's a bit slower and briefly needs room for both copies.
						</p>
						<p class="text-base-content/70">
							For instant moves, keep slskd's downloads and your music library on the same
							filesystem.
							{#if mount.path}<code class="text-base-content/60">{mount.path}</code>{/if}
						</p>
					</div>
				</div>
			{:else if mount}
				<div class="alert alert-warning items-start text-sm">
					<TriangleAlert class="size-5 shrink-0" aria-hidden="true" />
					<div class="space-y-1">
						<p>
							DroppedNeedle can't reach slskd's downloads folder, so finished downloads won't
							import.
							{MOUNT_REASONS[mount.reason] ?? mount.reason}
						</p>
						<details class="text-xs">
							<summary class="cursor-pointer font-semibold">How to set this up</summary>
							<p class="mt-1 text-base-content/70">
								Mount slskd's download directory into DroppedNeedle <strong>read-write</strong>, on
								the
								<strong>same disk</strong> as your music library (imports move files with an atomic
								rename). See the slskd setup guide (<code>docs/SLSKD_SETUP.md</code>).
							</p>
						</details>
					</div>
				</div>
			{/if}
		</section>

		<div class="flex justify-end">
			<button class="btn btn-primary" onclick={handleSave} disabled={save.isPending}>
				{#if save.isPending}<span class="loading loading-spinner loading-sm"></span>{/if}
				Save settings
			</button>
		</div>
	</DownloadClientCard>
{/if}
