<script lang="ts">
	import { Copy, Plus, Trash2, TriangleAlert, Waypoints } from 'lucide-svelte';

	import { authStore } from '$lib/stores/authStore.svelte';
	import { toastStore } from '$lib/stores/toast';
	import {
		getAppPasswordsQuery,
		getConnectAppsSettingsQuery
	} from '$lib/queries/connect-apps/ConnectAppsQueries.svelte';
	import {
		createAppPassword,
		revokeAppPassword,
		saveConnectAppsSettings
	} from '$lib/queries/connect-apps/ConnectAppsMutations.svelte';
	import type { AppPasswordView, ConnectAppsSettings } from '$lib/types';

	const settingsQuery = getConnectAppsSettingsQuery();
	const passwordsQuery = getAppPasswordsQuery();
	const save = saveConnectAppsSettings();
	const create = createAppPassword();
	const revoke = revokeAppPassword();

	// seeded once so a background refetch never clobbers in-flight edits
	let subsonicEnabled = $state(false);
	let jellyfinEnabled = $state(false);
	let transcodingEnabled = $state(true);
	let transcodeFormat = $state<'mp3' | 'opus'>('mp3');
	let transcodeMaxKbps = $state(320);
	let discoverMode = $state<'local-only' | 'lazy-mb' | 'use-scrobble-targets'>('local-only');
	let seeded = $state(false);

	let newName = $state('');
	let revealedSecret = $state<string | null>(null);
	let revealedName = $state('');
	let pendingRevoke = $state<AppPasswordView | null>(null);
	let revealDialog = $state<HTMLDialogElement>();
	let revokeDialog = $state<HTMLDialogElement>();

	// onclose clears state so the one-time secret never lingers after dismissal
	$effect(() => {
		if (!revealDialog) return;
		if (revealedSecret !== null) revealDialog.showModal();
		else if (revealDialog.open) revealDialog.close();
	});
	$effect(() => {
		if (!revokeDialog) return;
		if (pendingRevoke !== null) revokeDialog.showModal();
		else if (revokeDialog.open) revokeDialog.close();
	});

	const isAdmin = $derived(authStore.isAdmin);
	const origin = $derived(typeof window !== 'undefined' ? window.location.origin : '');
	const subsonicUrl = $derived(`${origin}/subsonic`);
	const jellyfinUrl = $derived(`${origin}/jellyfin`);
	const username = $derived(authStore.user?.username ?? '');

	const cap = $derived(passwordsQuery.data?.cap ?? 25);
	const activeCount = $derived(passwordsQuery.data?.active_count ?? 0);
	const atCap = $derived(activeCount >= cap);

	const showDisabledPanel = $derived(
		!isAdmin &&
			!(settingsQuery.data?.subsonic_enabled ?? false) &&
			!(settingsQuery.data?.jellyfin_enabled ?? false) &&
			activeCount === 0
	);

	const SUGGESTED_NAMES = [
		'Symfonium (phone)',
		'Feishin (desktop)',
		'Amperfy (phone)',
		'Finamp (tablet)',
		'Jellify (phone)',
		'Manet (iPad)'
	];
	const SUBSONIC_CLIENTS = 'Symfonium, Feishin, Amperfy, DSub, Substreamer, play:Sub, Tempo';
	const JELLYFIN_CLIENTS = 'Finamp, Jellify, Manet Music (iOS), Symfonium (Jellyfin mode)';
	const CLIENT_NODES = ['Finamp', 'Symfonium', 'Feishin', 'Amperfy', 'Jellify', 'Manet'];

	$effect(() => {
		const d = settingsQuery.data;
		if (d && !seeded) {
			subsonicEnabled = d.subsonic_enabled;
			jellyfinEnabled = d.jellyfin_enabled;
			transcodingEnabled = d.transcoding_enabled;
			transcodeFormat = d.transcode_default_format;
			transcodeMaxKbps = d.transcode_max_bitrate_kbps;
			discoverMode = d.discover_mode;
			seeded = true;
		}
	});

	function currentSettings(): ConnectAppsSettings {
		return {
			subsonic_enabled: subsonicEnabled,
			jellyfin_enabled: jellyfinEnabled,
			transcoding_enabled: transcodingEnabled,
			transcode_default_format: transcodeFormat,
			// a cleared number input binds to null; fall back so we never PUT null
			transcode_max_bitrate_kbps: transcodeMaxKbps ?? 320,
			advertise_server_name: settingsQuery.data?.advertise_server_name ?? 'DroppedNeedle',
			advertise_server_version: settingsQuery.data?.advertise_server_version ?? '10.10.6',
			discover_mode: discoverMode
		};
	}

	async function handleSave() {
		try {
			await save.mutateAsync(currentSettings());
			toastStore.show({ message: 'Connect Apps settings saved', type: 'success' });
		} catch {
			toastStore.show({ message: 'Could not save settings', type: 'error' });
		}
	}

	async function handleCreate() {
		const name = newName.trim();
		if (!name) {
			toastStore.show({ message: 'Give the app-password a name first', type: 'error' });
			return;
		}
		try {
			const result = await create.mutateAsync(name);
			revealedSecret = result.secret;
			revealedName = result.app_password.name;
			newName = '';
		} catch (err) {
			const status = (err as { status?: number })?.status;
			toastStore.show({
				message:
					status === 409 ? 'Limit reached - revoke one first' : 'Could not create app-password',
				type: 'error'
			});
		}
	}

	async function confirmRevoke() {
		const target = pendingRevoke;
		if (!target) return;
		try {
			await revoke.mutateAsync(target.id);
			toastStore.show({ message: `Revoked "${target.name}"`, type: 'success' });
		} catch {
			toastStore.show({ message: 'Could not revoke app-password', type: 'error' });
		} finally {
			pendingRevoke = null;
		}
	}

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			toastStore.show({ message: 'Copied', type: 'success' });
		} catch {
			toastStore.show({ message: 'Could not copy', type: 'error' });
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		const d = new Date(iso);
		return Number.isNaN(d.getTime()) ? '-' : d.toLocaleDateString();
	}
</script>

<section class="flex flex-col gap-6">
	<!-- inbound hero: apps converge into DroppedNeedle, the opposite of the outbound tabs -->
	<header class="connect-hero overflow-hidden rounded-box border border-accent/20 bg-base-200 p-6">
		<div class="flex items-center gap-2 text-accent">
			<Waypoints class="h-5 w-5" aria-hidden="true" />
			<h2 class="text-xl font-bold tracking-tight">Connect Apps</h2>
		</div>
		<p class="mt-1 max-w-2xl text-base-content/70">
			Let your favourite music apps connect <span class="font-semibold text-accent">to</span>
			DroppedNeedle and stream your library.
		</p>
		<p class="mt-1 max-w-2xl text-sm text-base-content/50">
			The Jellyfin, Navidrome and Plex tabs connect DroppedNeedle out to another server. This does
			the opposite: other apps connect in and play what is here.
		</p>

		<div class="inbound-diagram mt-5" aria-hidden="true">
			{#each CLIENT_NODES as node, i (node)}
				<span class="inbound-node" style="--i: {i}">{node}</span>
			{/each}
			<span class="inbound-core">
				<span class="inbound-core-dot"></span>
				DN
			</span>
		</div>
	</header>

	{#if settingsQuery.isLoading}
		<div class="skeleton h-40 w-full rounded-box"></div>
		<div class="skeleton h-56 w-full rounded-box"></div>
	{:else if settingsQuery.isError}
		<div class="alert alert-error" role="alert">
			<TriangleAlert class="h-5 w-5" aria-hidden="true" />
			<span>Could not load Connect Apps settings.</span>
		</div>
	{:else if showDisabledPanel}
		<div class="card border border-base-300 bg-base-200">
			<div class="card-body items-center text-center">
				<Waypoints class="h-8 w-8 text-base-content/40" aria-hidden="true" />
				<h3 class="card-title">Connect Apps is turned off</h3>
				<p class="max-w-md text-base-content/60">
					Ask your administrator to turn on the OpenSubsonic or Jellyfin API. Once it is on, create
					an app-password here to play your library in apps like Symfonium or Finamp.
				</p>
			</div>
		</div>
	{:else}
		<div class="card border border-base-300 bg-base-200">
			<div class="card-body gap-5">
				<h3 class="card-title text-base">Protocols</h3>

				<label class="flex items-center justify-between gap-4">
					<span>
						<span class="font-medium">OpenSubsonic API</span>
						<span class="block text-sm text-base-content/60">
							Symfonium, Feishin, Amperfy and other Subsonic apps.
						</span>
					</span>
					<input
						type="checkbox"
						class="toggle toggle-accent"
						aria-label="Enable OpenSubsonic API"
						bind:checked={subsonicEnabled}
						disabled={!isAdmin}
					/>
				</label>

				<label class="flex items-center justify-between gap-4">
					<span>
						<span class="font-medium">Jellyfin-compatible API</span>
						<span class="block text-sm text-base-content/60">
							Finamp, Jellify, Manet Music and Symfonium's Jellyfin mode.
						</span>
					</span>
					<input
						type="checkbox"
						class="toggle toggle-accent"
						aria-label="Enable Jellyfin API"
						bind:checked={jellyfinEnabled}
						disabled={!isAdmin}
					/>
				</label>

				<div class="divider my-0"></div>

				<label class="flex items-center justify-between gap-4">
					<span class="font-medium">On-the-fly transcoding</span>
					<input
						type="checkbox"
						class="toggle toggle-accent"
						aria-label="Enable transcoding"
						bind:checked={transcodingEnabled}
						disabled={!isAdmin}
					/>
				</label>

				{#if transcodingEnabled}
					<div class="grid gap-4 sm:grid-cols-2">
						<label class="form-control">
							<span class="label-text mb-1">Default format</span>
							<select
								class="select select-bordered"
								aria-label="Transcode format"
								bind:value={transcodeFormat}
								disabled={!isAdmin}
							>
								<option value="mp3">MP3</option>
								<option value="opus">Opus</option>
							</select>
						</label>
						<label class="form-control">
							<span class="label-text mb-1">Max bitrate (kbps)</span>
							<input
								type="number"
								min="32"
								max="1411"
								class="input input-bordered"
								aria-label="Max bitrate kbps"
								bind:value={transcodeMaxKbps}
								disabled={!isAdmin}
							/>
						</label>
					</div>
				{/if}

				<label class="form-control">
					<span class="label-text mb-1">Similar-songs discovery</span>
					<select
						class="select select-bordered"
						aria-label="Discovery mode"
						bind:value={discoverMode}
						disabled={!isAdmin}
					>
						<option value="local-only">Local only - same artist, no outbound calls</option>
						<option value="lazy-mb">Lazy MusicBrainz - fetch related artists once, cached</option>
						<option value="use-scrobble-targets"> Use Last.fm / ListenBrainz when linked </option>
					</select>
				</label>

				{#if isAdmin}
					<div class="card-actions justify-end">
						<button class="btn btn-accent" onclick={handleSave} disabled={save.isPending}>
							{#if save.isPending}
								<span class="loading loading-spinner loading-sm"></span>
							{/if}
							Save
						</button>
					</div>
				{:else}
					<p class="text-sm text-base-content/50">
						Only an administrator can change these. You can still manage your own app-passwords
						below.
					</p>
				{/if}
			</div>
		</div>

		<div class="card border border-base-300 bg-base-200">
			<div class="card-body gap-4">
				<div class="flex flex-wrap items-center justify-between gap-2">
					<h3 class="card-title text-base">App-passwords</h3>
					<span class="badge badge-ghost" aria-label="app-password count">
						{activeCount} / {cap}
					</span>
				</div>
				<p class="text-sm text-base-content/60">
					An app-password is a separate secret you give to one app, so your real account password
					stays private. You can revoke it any time. Use a different one per device.
				</p>

				{#if passwordsQuery.data && passwordsQuery.data.items.length > 0}
					<div class="overflow-x-auto">
						<table class="table table-sm">
							<thead>
								<tr>
									<th>Name</th>
									<th>Created</th>
									<th>Last used</th>
									<th>Last client</th>
									<th class="text-right">Action</th>
								</tr>
							</thead>
							<tbody>
								{#each passwordsQuery.data.items as pw (pw.id)}
									<tr>
										<td class="font-medium">{pw.name}</td>
										<td>{formatDate(pw.created_at)}</td>
										<td>{formatDate(pw.last_used_at)}</td>
										<td>{pw.last_client ?? '-'}</td>
										<td class="text-right">
											<button
												class="btn btn-ghost btn-xs text-error"
												aria-label={`Revoke ${pw.name}`}
												onclick={() => (pendingRevoke = pw)}
											>
												<Trash2 class="h-4 w-4" aria-hidden="true" />
												Revoke
											</button>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div
						class="rounded-box border border-dashed border-base-300 p-6 text-center text-base-content/60"
					>
						No app-passwords yet - create one to connect an app.
					</div>
				{/if}

				<div class="flex flex-wrap items-end gap-2">
					<label class="form-control flex-1">
						<span class="label-text mb-1">New app-password name</span>
						<input
							type="text"
							class="input input-bordered"
							list="connect-apps-suggested-names"
							placeholder="Symfonium (phone)"
							aria-label="New app-password name"
							bind:value={newName}
						/>
						<datalist id="connect-apps-suggested-names">
							{#each SUGGESTED_NAMES as suggestion (suggestion)}
								<option value={suggestion}></option>
							{/each}
						</datalist>
					</label>
					<button
						class="btn btn-accent"
						onclick={handleCreate}
						disabled={create.isPending || atCap}
						title={atCap ? 'Revoke one first' : undefined}
					>
						{#if create.isPending}
							<span class="loading loading-spinner loading-sm"></span>
						{:else}
							<Plus class="h-4 w-4" aria-hidden="true" />
						{/if}
						Create
					</button>
				</div>
			</div>
		</div>

		<div class="grid gap-4 lg:grid-cols-2">
			{#each [{ key: 'subsonic', label: 'OpenSubsonic', url: subsonicUrl, on: settingsQuery.data?.subsonic_enabled ?? false, clients: SUBSONIC_CLIENTS }, { key: 'jellyfin', label: 'Jellyfin', url: jellyfinUrl, on: settingsQuery.data?.jellyfin_enabled ?? false, clients: JELLYFIN_CLIENTS }] as proto (proto.key)}
				<div class="card border border-base-300 bg-base-200" class:opacity-60={!proto.on}>
					<div class="card-body gap-3">
						<h3 class="card-title text-base">
							{proto.label}
							{#if !proto.on}
								<span class="badge badge-sm badge-ghost">enable above to use</span>
							{/if}
						</h3>
						<label class="form-control">
							<span class="label-text mb-1">Server URL</span>
							<div class="join">
								<input
									class="input input-bordered join-item flex-1 font-mono text-sm"
									readonly
									value={proto.url}
									aria-label={`${proto.label} server URL`}
								/>
								<button
									class="btn btn-square join-item"
									aria-label={`Copy ${proto.label} URL`}
									onclick={() => copy(proto.url)}
								>
									<Copy class="h-4 w-4" aria-hidden="true" />
								</button>
							</div>
						</label>
						<p class="text-sm">
							<span class="text-base-content/60">Username:</span>
							<span class="font-mono">{username || 'your username'}</span>
						</p>
						<p class="text-sm text-base-content/60">
							Use your <strong>app-password</strong> (above) as the password / API key.
						</p>
						<p class="text-xs text-base-content/50">Tested clients: {proto.clients}</p>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<dialog
		bind:this={revealDialog}
		class="modal"
		onclose={() => (revealedSecret = null)}
		aria-label="New app-password"
	>
		<div class="modal-box">
			<h3 class="flex items-center gap-2 text-lg font-bold">
				<TriangleAlert class="h-5 w-5 text-warning" aria-hidden="true" />
				Copy your app-password now
			</h3>
			<p class="py-2 text-sm text-base-content/70">
				This is the only time "{revealedName}" will be shown. If you lose it, revoke it and create a
				new one.
			</p>
			<div class="join w-full">
				<input
					class="input input-bordered join-item flex-1 font-mono"
					readonly
					value={revealedSecret ?? ''}
					aria-label="App-password secret"
				/>
				<button
					class="btn btn-accent join-item"
					onclick={() => revealedSecret && copy(revealedSecret)}
				>
					<Copy class="h-4 w-4" aria-hidden="true" /> Copy
				</button>
			</div>
			<div class="modal-action">
				<button class="btn" onclick={() => revealDialog?.close()}>Done</button>
			</div>
		</div>
	</dialog>

	<dialog
		bind:this={revokeDialog}
		class="modal"
		onclose={() => (pendingRevoke = null)}
		aria-label="Confirm revoke"
	>
		<div class="modal-box">
			<h3 class="text-lg font-bold">Revoke "{pendingRevoke?.name}"?</h3>
			<p class="py-2 text-sm text-base-content/70">
				Any app or device using this app-password will be disconnected immediately and will need a
				new one.
			</p>
			<div class="modal-action">
				<button class="btn btn-ghost" onclick={() => revokeDialog?.close()}>Cancel</button>
				<button class="btn btn-error" onclick={confirmRevoke} disabled={revoke.isPending}>
					{#if revoke.isPending}
						<span class="loading loading-spinner loading-sm"></span>
					{/if}
					Revoke
				</button>
			</div>
		</div>
	</dialog>
</section>

<style>
	.inbound-diagram {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: 0.5rem 1.25rem;
	}
	.inbound-node {
		position: relative;
		padding: 0.25rem 0.7rem;
		border-radius: 9999px;
		font-size: 0.78rem;
		color: oklch(from var(--color-base-content) l c h / 0.7);
		background: oklch(from var(--color-base-content) l c h / 0.06);
		border: 1px solid oklch(from var(--color-accent) l c h / 0.25);
		animation: node-pulse 3s ease-in-out infinite;
		animation-delay: calc(var(--i) * 0.25s);
	}
	.inbound-core {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.45rem 0.9rem;
		border-radius: 9999px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--color-accent-content, var(--color-base-100));
		background: var(--color-accent);
		box-shadow:
			0 0 0 1px oklch(from var(--color-accent) l c h / 0.4),
			0 0 30px oklch(from var(--color-accent) l c h / 0.35);
	}
	.inbound-core-dot {
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 9999px;
		background: var(--color-accent-content, var(--color-base-100));
		animation: core-throb 2.4s ease-in-out infinite;
	}
	@keyframes node-pulse {
		0%,
		100% {
			border-color: oklch(from var(--color-accent) l c h / 0.2);
		}
		50% {
			border-color: oklch(from var(--color-accent) l c h / 0.6);
		}
	}
	@keyframes core-throb {
		0%,
		100% {
			transform: scale(1);
			opacity: 0.85;
		}
		50% {
			transform: scale(1.35);
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.inbound-node,
		.inbound-core-dot {
			animation: none;
		}
	}
</style>
