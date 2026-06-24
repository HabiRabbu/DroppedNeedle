<script lang="ts">
	import { Download } from 'lucide-svelte';
	import { requestAlbum } from '$lib/utils/albumRequest';
	import { colors } from '$lib/colors';

	interface Props {
		mbid: string;
		artistName: string;
		albumName: string;
		year?: number | null;
		artistMbid?: string;
		size?: 'sm' | 'md';
	}

	let { mbid, artistName, albumName, year, artistMbid, size = 'sm' }: Props = $props();

	let requesting = $state(false);

	async function handleRequest(e: MouseEvent) {
		e.stopPropagation();
		e.preventDefault();
		if (requesting) return;
		requesting = true;
		try {
			await requestAlbum(mbid, {
				artist: artistName || undefined,
				album: albumName,
				year: year ?? undefined,
				artistMbid
			});
		} finally {
			requesting = false;
		}
	}
</script>

<button
	type="button"
	class="btn btn-circle btn-sm {size === 'sm'
		? 'min-h-[36px] min-w-[36px]'
		: 'min-h-[44px] min-w-[44px]'} border-none shadow-sm active:scale-[0.95]"
	style="background-color: {colors.accent};"
	title={requesting ? 'Requesting...' : 'Request album'}
	aria-label="Request {albumName}"
	disabled={requesting}
	onclick={handleRequest}
>
	{#if requesting}
		<span class="loading loading-spinner loading-xs" style="color: {colors.secondary};"></span>
	{:else}
		<Download class={size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'} color={colors.secondary} />
	{/if}
</button>
