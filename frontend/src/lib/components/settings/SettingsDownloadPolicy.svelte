<script lang="ts">
	import {
		getDownloadPolicyQuery,
		saveDownloadPolicy
	} from '$lib/queries/downloads/DownloadClientsQueries.svelte';
	import { toastStore } from '$lib/stores/toast';
	import type { DownloadPolicySettings } from '$lib/types';

	import QualityRangeSlider from './QualityRangeSlider.svelte';

	const policyQuery = getDownloadPolicyQuery();
	const save = saveDownloadPolicy();

	let qualityMin = $state('mp3_320');
	let qualityMax = $state('lossless');
	let flacMp3Only = $state(true);
	let verifyDownloads = $state(true);
	let autoAccept = $state(0.7);
	let manualMin = $state(0.5);
	let maxConcurrent = $state(3);
	let maxFailover = $state(3);
	let autoRetryEnabled = $state(true);
	let autoRetryMax = $state(6);
	let usenetMinAge = $state(30);
	let seeded = $state(false);

	$effect(() => {
		const d = policyQuery.data;
		if (d && !seeded) {
			qualityMin = d.quality_min;
			qualityMax = d.quality_max;
			flacMp3Only = d.flac_mp3_only;
			verifyDownloads = d.verify_downloads;
			autoAccept = d.preflight_score_auto_accept;
			manualMin = d.preflight_score_manual_min;
			maxConcurrent = d.max_concurrent_downloads;
			maxFailover = d.max_failover_attempts;
			autoRetryEnabled = d.auto_retry_enabled;
			autoRetryMax = d.auto_retry_max_attempts;
			usenetMinAge = d.usenet_min_release_age_minutes;
			seeded = true;
		}
	});

	async function onSave() {
		const d = policyQuery.data;
		if (!d) return;
		const policy: DownloadPolicySettings = {
			...d,
			quality_min: qualityMin,
			quality_max: qualityMax,
			flac_mp3_only: flacMp3Only,
			verify_downloads: verifyDownloads,
			preflight_score_auto_accept: autoAccept,
			preflight_score_manual_min: manualMin,
			max_concurrent_downloads: maxConcurrent,
			max_failover_attempts: maxFailover,
			auto_retry_enabled: autoRetryEnabled,
			auto_retry_max_attempts: autoRetryMax,
			usenet_min_release_age_minutes: usenetMinAge
		};
		try {
			await save.mutateAsync(policy);
			toastStore.show({ message: 'Download policy saved', type: 'success' });
		} catch {
			toastStore.show({ message: 'Could not save download policy', type: 'error' });
		}
	}
</script>

<section class="card border border-base-300 bg-base-100">
	<div class="card-body gap-4">
		<div>
			<h3 class="font-semibold">Download policy</h3>
			<p class="text-sm text-base-content/70">
				Shared by every source - quality, what auto-downloads vs needs review, and resilience.
			</p>
		</div>

		<div class="form-control">
			<span class="label-text mb-2">Accepted quality range</span>
			<QualityRangeSlider bind:minKey={qualityMin} bind:maxKey={qualityMax} />
		</div>

		<label class="label cursor-pointer justify-start gap-3">
			<input type="checkbox" class="toggle toggle-sm toggle-primary" bind:checked={flacMp3Only} />
			<span class="label-text">Only accept FLAC and MP3</span>
		</label>
		<label class="label cursor-pointer justify-start gap-3">
			<input
				type="checkbox"
				class="toggle toggle-sm toggle-primary"
				bind:checked={verifyDownloads}
			/>
			<span class="label-text">Verify downloads (AcoustID release-group check)</span>
		</label>

		<div class="grid gap-4 sm:grid-cols-2">
			<label class="form-control">
				<span class="label-text">Auto-accept score (≥)</span>
				<input
					type="number"
					step="0.05"
					min="0"
					max="1"
					class="input input-bordered input-sm"
					bind:value={autoAccept}
				/>
			</label>
			<label class="form-control">
				<span class="label-text">Manual-review score (≥)</span>
				<input
					type="number"
					step="0.05"
					min="0"
					max="1"
					class="input input-bordered input-sm"
					bind:value={manualMin}
				/>
			</label>
			<label class="form-control">
				<span class="label-text">Max concurrent downloads</span>
				<input
					type="number"
					min="1"
					max="10"
					class="input input-bordered input-sm"
					bind:value={maxConcurrent}
				/>
			</label>
			<label class="form-control">
				<span class="label-text">Max failover attempts</span>
				<input
					type="number"
					min="1"
					max="10"
					class="input input-bordered input-sm"
					bind:value={maxFailover}
				/>
			</label>
			<label class="form-control">
				<span class="label-text">Auto-retry attempts</span>
				<input
					type="number"
					min="0"
					max="20"
					class="input input-bordered input-sm"
					bind:value={autoRetryMax}
					disabled={!autoRetryEnabled}
				/>
			</label>
			<label class="form-control">
				<span class="label-text">Usenet release age before blocklisting (min)</span>
				<input
					type="number"
					min="0"
					max="1440"
					class="input input-bordered input-sm"
					bind:value={usenetMinAge}
				/>
			</label>
		</div>

		<label class="label cursor-pointer justify-start gap-3">
			<input
				type="checkbox"
				class="toggle toggle-sm toggle-primary"
				bind:checked={autoRetryEnabled}
			/>
			<span class="label-text">Auto-retry failed downloads</span>
		</label>

		<div class="flex justify-end">
			<button
				type="button"
				class="btn btn-primary btn-sm"
				onclick={onSave}
				disabled={save.isPending}
			>
				Save
			</button>
		</div>
	</div>
</section>
