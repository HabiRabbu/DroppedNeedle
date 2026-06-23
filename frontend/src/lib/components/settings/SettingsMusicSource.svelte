<script lang="ts">
	import { musicSourceStore, type MusicSource } from '$lib/stores/musicSource';
	import { fromStore } from 'svelte/store';

	const source = fromStore(musicSourceStore);

	let saving = $state(false);
	let message = $state('');

	const currentSource = $derived(source.current.source);

	async function handleChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		const newSource = target.value as MusicSource;
		if (newSource === currentSource) return;
		saving = true;
		message = '';
		const ok = await musicSourceStore.save(newSource);
		if (ok) {
			message = 'Default music source updated';
			setTimeout(() => {
				message = '';
			}, 5000);
		} else {
			message = "Couldn't save the default music source.";
		}
		saving = false;
	}

	$effect(() => {
		musicSourceStore.load();
	});
</script>

<div class="card bg-base-200">
	<div class="card-body">
		<h2 class="card-title text-2xl">Primary Music Source</h2>
		<p class="text-base-content/70 mb-4">
			Choose which listening service powers your Home and Discover by default. You can also set
			this from your profile, and switch it on each page.
		</p>

		<fieldset class="fieldset">
			<legend class="fieldset-legend">Default source for your discovery data</legend>
			<select
				class="select select-primary w-full max-w-xs"
				value={currentSource}
				onchange={handleChange}
				disabled={saving}
			>
				<option value="listenbrainz">ListenBrainz</option>
				<option value="lastfm">Last.fm</option>
			</select>
			<p class="label text-base-content/60">
				Your Home and Discover use this source unless you switch it on the page.
			</p>
		</fieldset>

		{#if saving}
			<div class="flex items-center gap-2 mt-2">
				<span class="loading loading-spinner loading-sm"></span>
				<span class="text-sm text-base-content/70">Saving…</span>
			</div>
		{/if}

		{#if message}
			<div class="mt-2">
				<span class="text-sm {message.includes('Couldn') ? 'text-error' : 'text-success'}">
					{message}
				</span>
			</div>
		{/if}
	</div>
</div>
