<script lang="ts">
	import { BadgeCheck, Disc3, Files, Signal } from 'lucide-svelte';

	import type { ScoredCandidate } from '$lib/types';

	interface Props {
		candidate: ScoredCandidate;
		onPick?: () => void;
		picking?: boolean;
	}
	const { candidate, onPick, picking = false }: Props = $props();

	const RING_R = 26;
	const RING_C = 2 * Math.PI * RING_R;

	const percent = $derived(Math.round(candidate.final_score * 100));
	const fileCount = $derived(candidate.files.length);
	const freeSlot = $derived(candidate.files.some((f) => f.has_free_slot));
	const uploadSpeed = $derived(Math.max(0, ...candidate.files.map((f) => f.upload_speed)));

	const format = $derived.by(() => {
		const ext = (candidate.files[0]?.extension ?? '').toUpperCase();
		const bitrate = Math.max(0, ...candidate.files.map((f) => f.bitrate ?? 0));
		if (!ext) return 'AUDIO';
		return bitrate && !['FLAC', 'ALAC', 'WAV', 'APE', 'WV'].includes(ext)
			? `${ext} ${bitrate}`
			: ext;
	});

	const tierClass = $derived(
		candidate.tier === 'auto'
			? 'ring-accent text-accent'
			: candidate.tier === 'manual'
				? 'ring-warning text-warning'
				: 'ring-base-content/30 text-base-content/50'
	);

	const breakdown = $derived(
		`Coherence ${Math.round(candidate.coherence * 100)}% · ` +
			`File confidence ${Math.round(candidate.file_confidence * 100)}% · ` +
			`${freeSlot ? 'Free slot' : 'Queued'}${uploadSpeed ? ` · ${Math.round(uploadSpeed / 1000)} KB/s` : ''}`
	);

	// ring fills from empty to this target on mount via the from-only `ring-fill` keyframe
	const dashoffset = $derived(RING_C * (1 - Math.max(0, Math.min(1, candidate.final_score))));
</script>

<div class="sleeve-card flex items-center gap-4 rounded-box border border-base-300 bg-base-200 p-3">
	<div
		class="sleeve grid size-14 shrink-0 place-items-center rounded-md bg-base-300"
		aria-hidden="true"
	>
		<Disc3 class="size-7 text-base-content/60" />
	</div>

	<div class="min-w-0 flex-1">
		<p class="truncate font-semibold" title={candidate.parent_directory}>
			{candidate.parent_directory || 'Unknown folder'}
		</p>
		<p class="truncate text-sm text-base-content/60">{candidate.username}</p>
		<div class="mt-1.5 flex flex-wrap items-center gap-1.5">
			<span class="badge badge-sm" class:badge-success={candidate.tier !== 'rejected'}
				>{format}</span
			>
			<span class="badge badge-ghost badge-sm gap-1">
				<Files class="size-3" aria-hidden="true" />{fileCount}
				{fileCount === 1 ? 'track' : 'tracks'}
			</span>
			{#if uploadSpeed > 0}
				<span class="badge badge-ghost badge-sm gap-1" aria-label="Has upload speed">
					<Signal class="size-3" aria-hidden="true" />{Math.round(uploadSpeed / 1000)} KB/s
				</span>
			{/if}
			{#if freeSlot}
				<span
					class="badge badge-ghost badge-sm gap-1 text-success"
					aria-label="Free slot available"
				>
					<BadgeCheck class="size-3" aria-hidden="true" />slot
				</span>
			{/if}
		</div>
	</div>

	<div class="tooltip tooltip-left shrink-0" data-tip={breakdown}>
		<div class={`score-ring grid size-[64px] place-items-center rounded-full ring-1 ${tierClass}`}>
			<svg viewBox="0 0 64 64" class="absolute size-[64px] -rotate-90">
				<circle
					cx="32"
					cy="32"
					r={RING_R}
					fill="none"
					stroke="currentColor"
					stroke-width="4"
					class="opacity-15"
				/>
				<circle
					class="ring-progress"
					cx="32"
					cy="32"
					r={RING_R}
					fill="none"
					stroke="currentColor"
					stroke-width="4"
					stroke-linecap="round"
					stroke-dasharray={RING_C}
					stroke-dashoffset={dashoffset}
				/>
			</svg>
			<span class="text-sm font-bold tabular-nums">{percent}%</span>
		</div>
	</div>

	<button
		type="button"
		class="btn btn-primary btn-sm shrink-0"
		onclick={onPick}
		disabled={picking}
		aria-label={`Pick candidate from ${candidate.username}`}
	>
		{#if picking}<span class="loading loading-spinner loading-xs"></span>{/if}
		Pick
	</button>
</div>

<style>
	.sleeve-card {
		transform: perspective(900px) rotateY(-3deg);
		transform-style: preserve-3d;
		transition:
			transform 0.35s ease,
			box-shadow 0.35s ease;
		animation: fade-in-up 0.3s ease both;
	}
	.sleeve-card:hover {
		transform: perspective(900px) rotateY(0deg) translateY(-2px);
		box-shadow: 0 12px 30px oklch(from var(--color-base-300) l c h / 0.6);
	}
	.sleeve {
		transform: translateZ(20px) rotateY(6deg);
		box-shadow: 4px 4px 12px oklch(from var(--color-base-300) l c h / 0.7);
	}
	.score-ring {
		position: relative;
	}
	/* from-only keyframe animates to the element's own stroke-dashoffset */
	.ring-progress {
		animation: ring-fill 0.9s cubic-bezier(0.4, 0, 0.2, 1) both;
	}
	@keyframes ring-fill {
		from {
			stroke-dashoffset: 170;
		}
	}
	@keyframes fade-in-up {
		0% {
			opacity: 0;
			transform: perspective(900px) rotateY(-3deg) translateY(10px);
		}
		100% {
			opacity: 1;
			transform: perspective(900px) rotateY(-3deg) translateY(0);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.sleeve-card,
		.ring-progress {
			animation: none;
		}
	}
</style>
