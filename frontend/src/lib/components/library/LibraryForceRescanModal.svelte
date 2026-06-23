<script lang="ts">
	interface Props {
		scanning: boolean;
		onconfirm: () => void;
	}

	let { scanning, onconfirm }: Props = $props();

	let dialogEl = $state<HTMLDialogElement | null>(null);

	export function showModal() {
		dialogEl?.showModal();
	}

	export function close() {
		dialogEl?.close();
	}
</script>

<dialog bind:this={dialogEl} class="modal">
	<div class="modal-box">
		<h3 class="text-lg font-bold">Force full re-scan?</h3>
		<p class="py-4 text-base-content/70">
			This re-reads <strong>every</strong> file and re-fetches identities from MusicBrainz, ignoring the
			usual unchanged-file skip and clearing the identification cache. It fixes bad matches but takes
			longer than a normal scan. No files are deleted.
		</p>
		<div class="modal-action">
			<form method="dialog">
				<button class="btn btn-ghost">Cancel</button>
			</form>
			<button class="btn btn-error" onclick={onconfirm} disabled={scanning}>
				{#if scanning}
					<span class="loading loading-spinner loading-xs"></span>
				{/if}
				Force re-scan
			</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
