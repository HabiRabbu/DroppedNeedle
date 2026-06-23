<script lang="ts">
	import { derivedDownloadStatus } from '$lib/queries/downloads/downloadStatus';
	import { downloadStatusConfig } from '$lib/queries/downloads/downloadStatusConfig';
	import type { DownloadTask } from '$lib/types';

	let { task }: { task: DownloadTask } = $props();

	const derivedStatus = $derived(derivedDownloadStatus(task));
	const cfg = $derived(downloadStatusConfig[derivedStatus]);
	const label = $derived(
		derivedStatus === 'partial'
			? `Partial - ${task.files_completed}/${task.files_total} tracks`
			: cfg.label
	);
</script>

<span
	class="badge {cfg.badgeClass} badge-sm gap-1 {cfg.pulse ? 'animate-pulse' : ''}"
	aria-label="Status: {label}"
>
	<cfg.icon class="h-3 w-3" aria-hidden="true" />
	{label}
</span>
