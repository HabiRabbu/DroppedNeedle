<script lang="ts">
	import BaseImage from './BaseImage.svelte';
	import { API } from '$lib/constants';

	interface Props {
		mbid?: string;
		albumId?: string;
		coverVersion?: number;
		alt?: string;
		size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'hero' | 'full';
		lazy?: boolean;
		showPlaceholder?: boolean;
		className?: string;
		rounded?: 'none' | 'sm' | 'md' | 'lg' | 'xl' | 'full';
		customUrl?: string | null;
		remoteUrl?: string | null;
		onload?: () => void;
		testId?: string;
		source?: 'provider' | 'local';
		available?: boolean;
	}

	let {
		mbid = '',
		albumId = undefined,
		coverVersion = undefined,
		alt = 'Album',
		size = 'md',
		lazy = true,
		showPlaceholder = true,
		className = '',
		rounded = 'lg',
		customUrl = null,
		remoteUrl = null,
		onload = undefined,
		testId = undefined,
		source = 'provider',
		available = true
	}: Props = $props();

	let cachedLocalUrl = $derived(
		albumId && coverVersion !== undefined
			? API.library.cachedAlbumArtwork(albumId, coverVersion)
			: null
	);
</script>

<BaseImage
	{mbid}
	{alt}
	{size}
	{lazy}
	{showPlaceholder}
	{className}
	{rounded}
	customUrl={cachedLocalUrl ?? customUrl}
	{remoteUrl}
	{onload}
	{testId}
	source={cachedLocalUrl ? 'local' : source}
	{available}
	retryOnError={!cachedLocalUrl}
	transparentFallback={Boolean(cachedLocalUrl)}
	imageType="album"
/>
