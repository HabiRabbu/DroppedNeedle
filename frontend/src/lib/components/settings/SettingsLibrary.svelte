<script lang="ts">
	import { AlertTriangle } from 'lucide-svelte';
	import { getLibrarySettingsQuery } from '$lib/queries/library/LibraryQueries.svelte';
	import { saveLibrarySettings } from '$lib/queries/library/LibraryMutations.svelte';
	import LibraryPathEditor from '$lib/components/library/LibraryPathEditor.svelte';
	import LibraryNamingPreview from '$lib/components/library/LibraryNamingPreview.svelte';
	import LibraryScanButton from '$lib/components/library/LibraryScanButton.svelte';
	import LibraryForceRescanButton from '$lib/components/library/LibraryForceRescanButton.svelte';
	import LibraryScanScheduleControl from '$lib/components/library/LibraryScanScheduleControl.svelte';
	import { toastStore } from '$lib/stores/toast';

	const settingsQuery = getLibrarySettingsQuery();
	const save = saveLibrarySettings();

	let template = $state('');
	let acoustidKey = $state('');
	let seeded = $state(false);

	// Seed the editable fields once from the server; later refetches (after a
	// path add/remove) must not clobber unsaved template/key edits.
	$effect(() => {
		const d = settingsQuery.data;
		if (d && !seeded) {
			template = d.naming_template;
			acoustidKey = d.acoustid_api_key;
			seeded = true;
		}
	});

	const paths = $derived(settingsQuery.data?.library_paths ?? []);
	const hasKey = $derived(!!settingsQuery.data?.acoustid_api_key);

	async function handleSave() {
		const d = settingsQuery.data;
		if (!d) return;
		try {
			// Send the full record; the backend preserves the AcoustID key when the
			// masked sentinel is sent back unchanged.
			await save.mutateAsync({
				...d,
				library_paths: paths,
				naming_template: template,
				acoustid_api_key: acoustidKey
			});
			toastStore.show({ message: 'Library settings saved', type: 'success' });
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to save settings',
				type: 'error'
			});
		}
	}
</script>

<div class="space-y-6">
	<div>
		<h2 class="text-xl font-bold">Library</h2>
		<p class="text-sm text-base-content/60">
			Manage your music library paths, file naming, and scanning.
		</p>
	</div>

	{#if settingsQuery.isLoading}
		<div class="skeleton h-64 w-full rounded-box"></div>
	{:else if settingsQuery.isError}
		<div class="alert alert-error">
			Failed to load library settings: {settingsQuery.error.message}
		</div>
	{:else}
		{#if !hasKey}
			<div class="alert alert-warning">
				<AlertTriangle class="h-5 w-5" />
				<span class="text-sm">
					No AcoustID key - fingerprint identification is off for files without MusicBrainz tags.
					Add a key to enable it.
				</span>
			</div>
		{/if}

		<section class="space-y-2">
			<h3 class="font-semibold">Library paths</h3>
			<LibraryPathEditor {paths} />
		</section>

		<section class="space-y-2">
			<h3 class="font-semibold">Naming template</h3>
			<p class="text-xs text-base-content/60">
				Applies to downloaded imports only. Variables: {'{albumartist} {album} {year} {disc} {track} {title} {ext}'}.
			</p>
			<input
				class="input input-bordered w-full font-mono text-sm"
				bind:value={template}
				aria-label="Naming template"
			/>
			<LibraryNamingPreview {template} />
		</section>

		<section class="space-y-2">
			<h3 class="font-semibold">AcoustID API key</h3>
			<input
				type="password"
				class="input input-bordered w-full font-mono text-sm"
				bind:value={acoustidKey}
				placeholder="Enter AcoustID API key"
				aria-label="AcoustID API key"
			/>
		</section>

		<div>
			<button class="btn btn-primary" onclick={handleSave} disabled={save.isPending}>
				{#if save.isPending}<span class="loading loading-spinner loading-sm"></span>{/if}
				Save settings
			</button>
		</div>

		<div class="divider my-1"></div>

		<section class="space-y-2">
			<h3 class="font-semibold">Automatic scanning</h3>
			<p class="text-xs text-base-content/60">
				How often DroppedNeedle re-scans your library for new and changed files.
			</p>
			<LibraryScanScheduleControl />
		</section>

		<section class="space-y-2">
			<h3 class="font-semibold">Manual scan</h3>
			<div class="flex flex-wrap items-center gap-2">
				<LibraryScanButton
					hasPath={paths.length > 0}
					disabled={paths.length === 0}
					class="btn btn-outline gap-1"
					title={paths.length === 0 ? 'Add a library path first' : 'Start a library scan'}
				/>
				<LibraryForceRescanButton hasPath={paths.length > 0} />
			</div>
		</section>
	{/if}
</div>
