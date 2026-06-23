<script lang="ts">
	import type {
		DiscoverQueueEnrichment,
		YouTubeSearchResponse,
		YouTubeQuotaStatus
	} from '$lib/types';
	import YouTubeIcon from './YouTubeIcon.svelte';
	import { Settings, ExternalLink } from 'lucide-svelte';

	interface Props {
		enriching: boolean;
		enrichment?: DiscoverQueueEnrichment;
		ytSearching: boolean;
		ytSearchResult: YouTubeSearchResponse | null;
		quota: YouTubeQuotaStatus | null;
		compact?: boolean;
		onYtSearch: () => void;
		onNavigate: (path: string) => void;
	}

	let {
		enriching,
		enrichment,
		ytSearching,
		ytSearchResult,
		quota = null,
		compact = false,
		onYtSearch,
		onNavigate
	}: Props = $props();
</script>

{#if enriching}
	<div class="skeleton w-full rounded-xl" style="padding-bottom: 56.25%"></div>
{:else if enrichment?.youtube_url || ytSearchResult?.embed_url}
	{@const videoUrl = enrichment?.youtube_url ?? ytSearchResult?.embed_url}
	<div class="dq-video-wrap">
		<iframe
			src={videoUrl}
			title="Album preview"
			frameborder="0"
			allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
			allowfullscreen
			loading="lazy"
			class="absolute inset-0 w-full h-full"
		></iframe>
	</div>
	<div class="flex justify-between items-center mt-2 px-1 min-h-5">
		{#if enrichment?.youtube_search_url}
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="link link-hover text-xs text-base-content/40"
			>
				Search on YouTube <ExternalLink class="inline h-3 w-3" />
			</a>
		{/if}
		{#if quota && !compact}
			<span class="text-xs text-base-content/30">{quota.used} / {quota.limit} lookups today</span>
		{/if}
	</div>
{:else if ytSearching}
	<div class="dq-no-video text-base-content/40">
		<span class="loading loading-spinner loading-lg text-primary"></span>
		<p class="mt-2">{compact ? 'Searching…' : 'Searching for video preview…'}</p>
	</div>
{:else if ytSearchResult?.error === 'quota_exceeded'}
	<div class="dq-no-video text-base-content/40">
		{#if !compact}<YouTubeIcon class="dq-yt-icon" />{/if}
		<p>YouTube limit reached{compact ? '' : ' for today'}</p>
		{#if enrichment}
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn btn-outline btn-sm mt-2"
			>
				Search on YouTube
			</a>
		{/if}
	</div>
{:else if ytSearchResult?.error === 'not_found' || ytSearchResult?.error === 'request_failed'}
	<div class="dq-no-video text-base-content/40">
		{#if !compact}<YouTubeIcon class="dq-yt-icon" />{/if}
		<p>No video found</p>
		{#if enrichment}
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn btn-outline btn-sm mt-2"
			>
				Search on YouTube
			</a>
		{/if}
	</div>
{:else if enrichment?.youtube_search_available}
	<div class="dq-no-video text-base-content/40">
		<button class="btn {compact ? '' : 'btn-lg'} gap-2 dq-yt-btn" onclick={onYtSearch}>
			<YouTubeIcon />
			Find Video{compact ? '' : ' Preview'}
		</button>
		{#if quota}
			<div class="flex flex-col items-center gap-1 w-full max-w-64 mt-3">
				<progress class="progress progress-primary w-full" value={quota.used} max={quota.limit}
				></progress>
				<span class="text-xs text-base-content/40">
					{quota.remaining} / {quota.limit} lookups remaining today
				</span>
			</div>
		{:else if !compact}
			<p class="mt-2 text-xs text-base-content/30">Uses YouTube Data API</p>
		{/if}
		{#if enrichment?.youtube_search_url}
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="link link-hover text-xs text-base-content/40 mt-4"
			>
				or search YouTube manually <ExternalLink class="inline h-3 w-3" />
			</a>
		{/if}
	</div>
{:else if enrichment}
	<div class="dq-no-video text-base-content/40">
		{#if compact}
			<p>No preview available</p>
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn btn-outline btn-sm mt-2">Search on YouTube</a
			>
		{:else}
			<YouTubeIcon class="dq-yt-icon-color" />
			<p>No video preview available</p>
			<button
				class="btn btn-sm btn-primary gap-1 mt-2"
				onclick={(e) => {
					e.preventDefault();
					onNavigate('/settings?tab=youtube');
				}}
			>
				<Settings class="h-4 w-4" />
				Add YouTube API Key
			</button>
			<a
				href={enrichment.youtube_search_url}
				target="_blank"
				rel="noopener noreferrer"
				class="btn btn-outline btn-sm mt-2"
			>
				Search on YouTube
			</a>
		{/if}
	</div>
{/if}

<style>
	.dq-video-wrap {
		position: relative;
		width: 100%;
		padding-bottom: 56.25%;
		border-radius: 0.75rem;
		overflow: hidden;
		background: var(--color-base-200);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
	}

	.dq-no-video {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 3rem 2rem;
		background: linear-gradient(
			135deg,
			color-mix(in srgb, var(--color-base-content) 3%, transparent),
			color-mix(in srgb, var(--color-base-content) 1%, transparent)
		);
		border-radius: 0.75rem;
		font-size: 0.85rem;
	}

	:global(.dq-yt-icon) {
		width: 2.5rem;
		height: 2.5rem;
		color: var(--color-youtube);
		opacity: 0.7;
		margin-bottom: 0.75rem;
		animation: pulse-icon 3s cubic-bezier(0.4, 0, 0.6, 1) infinite;
	}

	@keyframes pulse-icon {
		0%,
		100% {
			opacity: 0.7;
			transform: scale(1);
		}
		50% {
			opacity: 0.4;
			transform: scale(0.95);
		}
	}

	:global(.dq-yt-icon-color) {
		width: 3rem;
		height: 3rem;
		color: var(--color-youtube);
		margin-bottom: 0.75rem;
		filter: drop-shadow(0 2px 4px color-mix(in srgb, var(--color-youtube) 20%, transparent));
	}

	.dq-yt-btn {
		background: var(--color-youtube);
		border: none;
		color: var(--color-base-100);
		font-weight: 600;
	}

	.dq-yt-btn:hover {
		background: var(--color-youtube-hover);
		color: var(--color-base-100);
	}
</style>
