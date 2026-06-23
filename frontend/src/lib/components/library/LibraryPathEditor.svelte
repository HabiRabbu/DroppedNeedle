<script lang="ts">
	import { X, FolderPlus } from 'lucide-svelte';
	import { addLibraryPath, removeLibraryPath } from '$lib/queries/library/LibraryMutations.svelte';
	import { toastStore } from '$lib/stores/toast';

	interface Props {
		paths: string[];
	}

	let { paths }: Props = $props();

	const add = addLibraryPath();
	const remove = removeLibraryPath();

	let newPath = $state('');
	let confirmRemove = $state<string | null>(null);

	async function handleAdd() {
		const p = newPath.trim();
		if (!p) return;
		try {
			await add.mutateAsync(p);
			newPath = '';
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to add path',
				type: 'error'
			});
		}
	}

	async function performRemove(path: string) {
		try {
			await remove.mutateAsync(path);
		} catch (e) {
			toastStore.show({
				message: e instanceof Error ? e.message : 'Failed to remove path',
				type: 'error'
			});
		}
	}

	function handleRemove(path: string) {
		// Removing the only remaining path can orphan scan data (R5/Q1-B) — confirm.
		if (paths.length <= 1) {
			confirmRemove = path;
			return;
		}
		void performRemove(path);
	}

	function confirmedRemove() {
		const p = confirmRemove;
		confirmRemove = null;
		if (p) void performRemove(p);
	}
</script>

<div class="space-y-2">
	{#if paths.length === 0}
		<p class="text-sm text-base-content/50">
			No library paths yet — add one below to scan your music.
		</p>
	{:else}
		<ul class="space-y-1">
			{#each paths as path (path)}
				<li class="flex items-center justify-between gap-2 rounded-box bg-base-200 px-3 py-2">
					<span class="truncate font-mono text-sm" title={path}>{path}</span>
					<button
						class="btn btn-ghost btn-xs btn-circle"
						onclick={() => handleRemove(path)}
						disabled={remove.isPending}
						aria-label="Remove {path}"
					>
						<X class="h-4 w-4" />
					</button>
				</li>
			{/each}
		</ul>
	{/if}

	{#if confirmRemove}
		<div class="alert alert-warning">
			<span class="text-sm">Remove the only library path? Scan data may be orphaned.</span>
			<div class="flex gap-2">
				<button class="btn btn-error btn-xs" onclick={confirmedRemove}>Remove</button>
				<button class="btn btn-ghost btn-xs" onclick={() => (confirmRemove = null)}>Cancel</button>
			</div>
		</div>
	{/if}

	<div class="join w-full">
		<input
			class="input input-bordered input-sm join-item flex-1 font-mono"
			placeholder="/music"
			bind:value={newPath}
			onkeydown={(e) => e.key === 'Enter' && handleAdd()}
			aria-label="New library path"
		/>
		<button
			class="btn btn-primary btn-sm join-item gap-1"
			onclick={handleAdd}
			disabled={add.isPending || !newPath.trim()}
		>
			<FolderPlus class="h-4 w-4" /> Add path
		</button>
	</div>
</div>
