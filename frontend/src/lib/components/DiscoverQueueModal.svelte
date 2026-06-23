<script lang="ts">
	import { X, Play, Info, ArrowRight, BookOpen } from 'lucide-svelte';
	import { goto } from '$app/navigation';
	import { fly } from 'svelte/transition';
	import { API } from '$lib/constants';
	import {
		getQueueCachedData,
		setQueueCachedData,
		removeQueueCachedData,
		type QueueCacheData
	} from '$lib/utils/discoverQueueCache';
	import type { MusicSource } from '$lib/stores/musicSource';
	import { authStore } from '$lib/stores/authStore.svelte';
	import { discoverQueueStatusStore } from '$lib/stores/discoverQueueStatus';
	import { getCacheTTLs } from '$lib/stores/cacheTtl';
	import { resolveQueueCloseAction } from '$lib/utils/discoverQueueActions';
	import { isAbortError } from '$lib/utils/errorHandling';
	import { api } from '$lib/api/client';
	import AlbumImage from './AlbumImage.svelte';
	import DQVideoSection from './DQVideoSection.svelte';
	import DQInfoGrid from './DQInfoGrid.svelte';
	import type {
		DiscoverQueueEnrichment,
		DiscoverQueueItemFull,
		DiscoverQueueResponse,
		YouTubeSearchResponse,
		YouTubeQuotaStatus
	} from '$lib/types';
	import { SvelteMap } from 'svelte/reactivity';

	let { open = $bindable(false), source }: { open: boolean; source: MusicSource } = $props();

	function emptyEnrichment(): DiscoverQueueEnrichment {
		return {
			artist_mbid: null,
			release_date: null,
			country: null,
			tags: [],
			youtube_url: null,
			youtube_search_url: '',
			youtube_search_available: false,
			artist_description: null,
			listen_count: null
		};
	}

	let dialogEl: HTMLDialogElement | undefined = $state();
	let queue: DiscoverQueueItemFull[] = $state([]);
	let currentIndex: number = $state(0);
	let loading: boolean = $state(false);
	let queueId: string = $state('');
	let mobileTab: 'video' | 'info' | 'bio' = $state('video');
	let bioExpanded: boolean = $state(false);
	let nextDebounce: ReturnType<typeof setTimeout> | null = $state(null);
	let ytSearching: boolean = $state(false);
	let ytSearchResult: YouTubeSearchResponse | null = $state(null);
	let ytQuota: YouTubeQuotaStatus | null = $state(null);

	let enrichmentCache = new SvelteMap<string, DiscoverQueueEnrichment>();
	let inFlightEnrich = new SvelteMap<string, Promise<DiscoverQueueEnrichment | null>>();
	let ytSearchCache = new SvelteMap<string, YouTubeSearchResponse>();
	let abortController: AbortController | null = null;

	let currentItem: DiscoverQueueItemFull | undefined = $derived(queue[currentIndex]);
	let enrichment: DiscoverQueueEnrichment | undefined = $derived(currentItem?.enrichment);
	let artistNavigationMbid: string = $derived(
		currentItem?.artist_mbid || enrichment?.artist_mbid || ''
	);
	let enriching: boolean = $derived(currentItem != null && !currentItem.enrichment);
	let isLastItem: boolean = $derived(currentIndex >= queue.length - 1);
	let progressText: string = $derived(
		queue.length > 0 ? `${currentIndex + 1} of ${queue.length}` : ''
	);
	let progressFraction: number = $derived(queue.length > 0 ? (currentIndex + 1) / queue.length : 0);

	let queueLoaded: boolean = $state(false);

	function cleanup() {
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
		inFlightEnrich.clear();
		enrichmentCache.clear();
		ytSearchCache.clear();
		queueLoaded = false;
	}

	$effect(() => {
		if (!dialogEl) return;
		if (open) {
			abortController = new AbortController();
			dialogEl.showModal();
			fetchQuota();
			if (!queueLoaded) {
				queueLoaded = true;
				loadQueue();
			}
		} else {
			if (dialogEl.open) dialogEl.close();
			cleanup();
		}
	});

	function handleClose() {
		if (!open) return;
		if (queue.length === 0 || isLastItem) {
			handleEndQueue();
			return;
		}
		saveQueueToStorage();
		open = false;
	}

	function navigateTo(path: string) {
		const action = resolveQueueCloseAction({ queueLength: queue.length, isLastItem });
		if (action === 'save') {
			saveQueueToStorage();
		}
		open = false;
		goto(path);
	}

	async function loadQueue() {
		const cached = loadQueueFromStorage();
		if (cached) {
			queue = cached.items;
			currentIndex = cached.currentIndex;
			queueId = cached.queueId;
			await validateCachedQueue();
			enrichCurrentAndNext();
			return;
		}
		await fetchNewQueue();
	}

	async function fetchNewQueue() {
		if (loading) return;
		loading = true;
		try {
			const data = await api.get<DiscoverQueueResponse>(API.discoverQueue(source), {
				signal: abortController?.signal
			});
			queue = data.items.map((item) => ({ ...item }));
			queueId = data.queue_id;
			currentIndex = 0;
			enrichmentCache.clear();
			inFlightEnrich.clear();
			saveQueueToStorage();
			enrichCurrentAndNext();
			discoverQueueStatusStore.markConsumed();
			if (getCacheTTLs().discoverQueueAutoGenerate) {
				discoverQueueStatusStore.triggerGenerate(false, source);
			}
		} catch (e) {
			if (isAbortError(e)) return;
		} finally {
			loading = false;
		}
	}

	async function validateCachedQueue() {
		if (queue.length === 0) return;
		try {
			const mbids = queue.map((i) => i.release_group_mbid);
			const data = await api.global.post<{ in_library?: string[] }>(
				API.discoverQueueValidate(),
				{ release_group_mbids: mbids },
				{ signal: abortController?.signal }
			);
			const inLibrary = new Set(data.in_library || []);
			if (inLibrary.size > 0) {
				queue = queue.filter((i) => !inLibrary.has(i.release_group_mbid));
				if (currentIndex >= queue.length) currentIndex = Math.max(0, queue.length - 1);
			}
			if (queue.length === 0) {
				await fetchNewQueue();
			}
		} catch {
			/* empty */
		}
	}

	async function enrichCurrentAndNext() {
		if (queue.length === 0) return;
		await enrichItem(currentIndex);
		for (let i = 1; i <= 2; i++) {
			if (currentIndex + i < queue.length) {
				enrichItem(currentIndex + i);
			}
		}
	}

	async function enrichItem(index: number) {
		const item = queue[index];
		if (!item || item.enrichment) return;

		const mbid = item.release_group_mbid;
		const cached = enrichmentCache.get(mbid);
		if (cached) {
			queue[index] = { ...item, enrichment: cached };
			return;
		}

		const existing = inFlightEnrich.get(mbid);
		if (existing) {
			const result = await existing;
			if (result && queue[index]?.release_group_mbid === mbid && !queue[index]?.enrichment) {
				queue[index] = { ...queue[index], enrichment: result };
			}
			return;
		}

		const signal = abortController?.signal;
		const promise = (async (): Promise<DiscoverQueueEnrichment | null> => {
			try {
				const data = await api.get<DiscoverQueueEnrichment>(API.discoverQueueEnrich(mbid), {
					signal
				});
				enrichmentCache.set(mbid, data);
				if (queue[index]?.release_group_mbid === mbid) {
					queue[index] = { ...queue[index], enrichment: data };
				}
				return data;
			} catch (e) {
				if (isAbortError(e)) return null;
				if (queue[index]?.release_group_mbid === mbid && !queue[index]?.enrichment) {
					queue[index] = { ...queue[index], enrichment: emptyEnrichment() };
				}
				return null;
			} finally {
				inFlightEnrich.delete(mbid);
			}
		})();

		inFlightEnrich.set(mbid, promise);
		await promise;
	}

	function handleNext() {
		if (nextDebounce) return;
		nextDebounce = setTimeout(() => {
			nextDebounce = null;
		}, 300);

		if (isLastItem) return;
		currentIndex++;
		bioExpanded = false;
		mobileTab = 'video';
		resetYtSearch();
		enrichCurrentAndNext();
		saveQueueToStorage();
	}

	async function handleIgnore() {
		const item = currentItem;
		if (!item) return;

		try {
			await api.global.post(
				API.discoverQueueIgnore(),
				{
					release_group_mbid: item.release_group_mbid,
					artist_mbid: item.artist_mbid,
					release_name: item.album_name,
					artist_name: item.artist_name
				},
				{ signal: abortController?.signal }
			);
		} catch {
			/* empty */
		}

		queue = queue.filter((_, i) => i !== currentIndex);
		if (currentIndex >= queue.length) currentIndex = Math.max(0, queue.length - 1);
		bioExpanded = false;
		resetYtSearch();
		enrichCurrentAndNext();
		saveQueueToStorage();
	}

	function handleEndQueue() {
		queue = [];
		currentIndex = 0;
		queueId = '';
		enrichmentCache.clear();
		inFlightEnrich.clear();
		ytSearchCache.clear();
		removeQueueCachedData(authStore.user?.id ?? 'anon', source);
		if (getCacheTTLs().discoverQueueAutoGenerate) {
			discoverQueueStatusStore.triggerGenerate(false, source);
		}
		open = false;
	}

	function saveQueueToStorage() {
		setQueueCachedData(
			{
				items: queue.map((item) => ({ ...item })),
				currentIndex,
				queueId
			},
			authStore.user?.id ?? 'anon',
			source
		);
	}

	function loadQueueFromStorage(): QueueCacheData | null {
		const cached = getQueueCachedData(authStore.user?.id ?? 'anon', source);
		if (!cached) return null;
		return cached.data;
	}

	function truncateText(text: string, maxLen: number): string {
		if (text.length <= maxLen) return text;
		return text.slice(0, maxLen).trimEnd() + '...';
	}

	function resetYtSearch() {
		ytSearching = false;
		ytSearchResult = null;
	}

	async function fetchQuota() {
		try {
			ytQuota = await api.get<YouTubeQuotaStatus>(API.discoverQueueYoutubeQuota(), {
				signal: abortController?.signal
			});
		} catch {
			/* empty */
		}
	}

	async function handleYtSearch() {
		if (!currentItem || ytSearching) return;
		const cacheKey = `${currentItem.artist_name}|${currentItem.album_name}`;
		const cached = ytSearchCache.get(cacheKey);
		if (cached) {
			ytSearchResult = cached;
			return;
		}

		ytSearching = true;
		ytSearchResult = null;
		try {
			const data = await api.get<YouTubeSearchResponse>(
				API.discoverQueueYoutubeSearch(currentItem.artist_name, currentItem.album_name),
				{ signal: abortController?.signal }
			);
			ytSearchCache.set(cacheKey, data);
			ytSearchResult = data;
		} catch {
			ytSearchResult = { video_id: null, embed_url: null, error: 'request_failed', cached: false };
		} finally {
			ytSearching = false;
			fetchQuota();
		}
	}
</script>

<dialog bind:this={dialogEl} class="modal" onclose={handleClose}>
	<div
		class="modal-box w-[92vw] max-w-4xl max-h-[80vh] sm:max-w-4xl max-sm:w-screen max-sm:max-w-full max-sm:max-h-screen max-sm:rounded-none flex flex-col p-0! overflow-hidden rounded-2xl bg-base-100 shadow-2xl relative"
	>
		<div
			class="absolute top-0 inset-x-0 h-0.5 bg-linear-to-r from-primary via-secondary to-primary z-10 rounded-t-2xl"
		></div>

		{#if loading}
			<div class="flex flex-col items-center justify-center py-16 px-8">
				<span class="loading loading-spinner loading-lg text-primary"></span>
				<p class="mt-4 text-base-content/60">Building your discovery queue...</p>
			</div>
		{:else if queue.length === 0}
			<div class="flex flex-col items-center justify-center py-16 px-8">
				<p class="text-base-content/60">No albums to discover right now.</p>
				<button class="btn btn-primary mt-4" onclick={handleEndQueue}>Try Again</button>
			</div>
		{:else if currentItem}
			{#key currentItem.release_group_mbid}
				<div in:fly={{ x: 20, duration: 300 }} class="flex flex-col flex-auto min-h-0 w-full">
					<div class="flex justify-between items-start pt-5 px-6 max-sm:pt-4 max-sm:px-4 shrink-0">
						<div class="flex flex-col gap-0.5 min-w-0">
							{#if currentItem.recommendation_reason}
								<span
									class="text-[0.65rem] font-semibold uppercase tracking-widest text-primary/70 font-mono mb-1"
									>{currentItem.recommendation_reason}</span
								>
							{/if}
							<div class="flex items-center gap-2">
								<button
									class="text-2xl font-extrabold text-base-content text-left bg-transparent border-none p-0 cursor-pointer leading-tight whitespace-nowrap overflow-hidden text-ellipsis max-w-full tracking-tight transition-colors duration-200 hover:text-primary"
									onclick={() => navigateTo(`/album/${currentItem.release_group_mbid}`)}
								>
									{currentItem.album_name}
								</button>
								{#if currentItem.is_wildcard}
									<span class="badge badge-sm badge-warning">Wildcard</span>
								{/if}
							</div>
							{#if artistNavigationMbid}
								<button
									class="text-sm text-base-content/60 text-left bg-transparent border-none p-0 cursor-pointer uppercase tracking-wide font-semibold transition-colors duration-200 hover:text-primary"
									onclick={() => navigateTo(`/artist/${artistNavigationMbid}`)}
								>
									{currentItem.artist_name}
								</button>
							{:else}
								<span class="text-sm text-base-content/60 uppercase tracking-wide font-semibold"
									>{currentItem.artist_name}</span
								>
							{/if}
						</div>
						<div class="flex items-center gap-2 shrink-0">
							<div class="w-18 h-1 rounded-full bg-base-content/20 overflow-hidden">
								<div
									class="h-full rounded-full `bg-linear-to-r from-primary to-secondary transition-all duration-400"
									style="width: {progressFraction * 100}%"
								></div>
							</div>
							<span
								class="text-xs text-base-content/45 whitespace-nowrap font-mono px-2 py-0.5 rounded-full bg-base-content/5 border border-base-content/5"
								>{progressText}</span
							>
							<button class="btn btn-sm btn-circle btn-ghost" onclick={handleClose}
								><X class="h-4 w-4" /></button
							>
						</div>
					</div>

					<div
						class="flex-1 overflow-y-auto min-h-0 p-4 px-6 max-sm:py-3 max-sm:px-4 hidden lg:block"
					>
						<div class="grid grid-cols-[260px_1fr] gap-6 items-start">
							<div class="flex flex-col">
								<button
									class="bg-transparent border-none p-0 cursor-pointer rounded-xl overflow-hidden shadow-xl transition-transform duration-300 hover:scale-[1.03] hover:-translate-y-1"
									onclick={() => navigateTo(`/album/${currentItem.release_group_mbid}`)}
								>
									<AlbumImage
										mbid={currentItem.release_group_mbid}
										alt={currentItem.album_name}
										size="full"
										lazy={false}
										rounded="none"
										className="w-65 `h-65 object-cover block"
									/>
								</button>

								<div
									class="mt-3 p-3 bg-base-100/30 backdrop-blur-md rounded-xl border border-base-content/5 shadow-sm"
								>
									{#if enriching}
										<div class="flex flex-col gap-2">
											<div class="skeleton h-4 w-3/4 rounded"></div>
											<div class="skeleton h-4 w-1/2 rounded"></div>
											<div class="skeleton h-3 w-2/3 rounded"></div>
										</div>
									{:else if enrichment}
										<DQInfoGrid {enrichment} inLibrary={currentItem.in_library} />
									{/if}
								</div>
							</div>

							<div class="flex flex-col">
								<DQVideoSection
									{enriching}
									{enrichment}
									{ytSearching}
									{ytSearchResult}
									quota={ytQuota}
									onYtSearch={handleYtSearch}
									onNavigate={navigateTo}
								/>
							</div>
						</div>

						{#if enriching}
							<div class="skeleton h-12 w-full rounded-lg mt-4"></div>
						{:else if enrichment?.artist_description}
							<div class="mt-3">
								<p class="text-xs leading-relaxed text-base-content/55">
									{#if bioExpanded}
										{enrichment.artist_description}
									{:else}
										{truncateText(enrichment.artist_description, 300)}
									{/if}
								</p>
								{#if enrichment.artist_description.length > 300}
									<button
										class="text-xs text-primary bg-transparent border-none p-0 mt-1 cursor-pointer hover:underline"
										onclick={() => (bioExpanded = !bioExpanded)}
									>
										{bioExpanded ? 'Show less' : 'Read more'}
									</button>
								{/if}
							</div>
						{/if}
					</div>

					<div
						class="flex-1 overflow-y-auto min-h-0 p-4 px-6 max-sm:py-3 max-sm:px-4 flex flex-col gap-3 items-center lg:hidden"
					>
						<button
							class="bg-transparent border-none p-0 cursor-pointer rounded-xl overflow-hidden shadow-xl"
							onclick={() => navigateTo(`/album/${currentItem.release_group_mbid}`)}
						>
							<AlbumImage
								mbid={currentItem.release_group_mbid}
								alt={currentItem.album_name}
								size="full"
								lazy={false}
								rounded="none"
								className="w-full max-w-55 aspect-square object-cover block"
							/>
						</button>

						<div role="tablist" class="tabs tabs-boxed tabs-sm mt-3">
							<button
								role="tab"
								class="tab"
								class:tab-active={mobileTab === 'video'}
								onclick={() => (mobileTab = 'video')}
							>
								<Play class="h-3 w-3" /> Video
							</button>
							<button
								role="tab"
								class="tab"
								class:tab-active={mobileTab === 'info'}
								onclick={() => (mobileTab = 'info')}
							>
								<Info class="h-3 w-3" /> Info
							</button>
							<button
								role="tab"
								class="tab"
								class:tab-active={mobileTab === 'bio'}
								onclick={() => (mobileTab = 'bio')}
							>
								<BookOpen class="h-3 w-3" /> Bio
							</button>
						</div>

						<div class="min-h-30 w-full">
							{#if enriching}
								<div class="skeleton h-40 w-full rounded-lg"></div>
							{:else if mobileTab === 'video'}
								<DQVideoSection
									{enriching}
									{enrichment}
									{ytSearching}
									{ytSearchResult}
									quota={ytQuota}
									compact={true}
									onYtSearch={handleYtSearch}
									onNavigate={navigateTo}
								/>
							{:else if mobileTab === 'info' && enrichment}
								<DQInfoGrid {enrichment} />
							{:else if mobileTab === 'bio'}
								{#if enrichment?.artist_description}
									<p class="text-sm text-base-content/70">{enrichment.artist_description}</p>
								{:else}
									<p class="text-sm text-base-content/50">No biography available.</p>
								{/if}
							{/if}
						</div>
					</div>

					<div
						class="flex justify-between items-center shrink-0 py-3 px-6 max-sm:py-3 max-sm:px-4 max-sm:flex-col max-sm:gap-2 border-t border-base-content/5 bg-base-content/"
					>
						<button class="btn btn-sm btn-soft btn-error" onclick={handleIgnore}>
							<X class="h-4 w-4" />
							Not for me
						</button>
						<div class="flex items-center gap-2 max-sm:w-full max-sm:justify-center">
							<button
								class="btn btn-sm btn-ghost"
								onclick={() => navigateTo(`/album/${currentItem.release_group_mbid}`)}
							>
								View Album
							</button>
							{#if isLastItem}
								<button class="btn btn-primary" onclick={handleEndQueue}> End Queue </button>
							{:else}
								<button class="btn btn-primary" onclick={handleNext}
									>Next <ArrowRight class="h-4 w-4" /></button
								>
							{/if}
						</div>
					</div>
				</div>
			{/key}
		{/if}
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
