/**
 * Just-in-time hydration for radio queue items that need external resolution:
 * YouTube items get a video id. A look-ahead window of 3 keeps resolution
 * invisible; unresolvable tracks are removed from the queue before they'd cause
 * dead air.
 *
 * Previews are NOT a player tier (cross-origin clips are muted by the player's
 * Web Audio graph), so nothing here downgrades to a preview - un-resolvable
 * YouTube tracks are simply dropped. Preview stations play in the floating
 * widget (deckSampler) instead.
 *
 * The launcher resolves the FIRST playable track inline via resolveRadioPatch
 * before starting playback - the player advances through unplayable items in
 * milliseconds, far faster than this timer, so the head must never be a
 * placeholder (the "Several tracks failed" bug, owner-reported 2026-07-03).
 */
import { API } from '$lib/constants';
import { api } from '$lib/api/client';
import { playerStore } from '$lib/stores/player.svelte';
import { radioSession } from '$lib/stores/radioSession.svelte';
import { extendRadio } from '$lib/player/launchRadio';
import type { QueueItem } from '$lib/player/types';

const LOOKAHEAD = 3;
const EXTEND_THRESHOLD = 3;
const TICK_MS = 2000;

type YtSearchResponse = { video_id?: string; embed_url?: string; error?: string };

let timer: ReturnType<typeof setInterval> | null = null;
let hydrating = new Set<string>();
let ytConfiguredForSession = false;

export function needsHydration(item: QueueItem): boolean {
	if (!item.playlistTrackId?.startsWith('radio:')) return false;
	return item.sourceType === 'youtube' && !item.trackSourceId;
}

/**
 * Resolve one radio placeholder to something playable.
 * Returns the patch to apply, or null when the track has no playable source.
 */
export async function resolveRadioPatch(item: QueueItem): Promise<Partial<QueueItem> | null> {
	if (item.sourceType !== 'youtube' || item.trackSourceId) return {};
	try {
		const data = await api.global.get<YtSearchResponse>(
			API.discoverQueueYoutubeTrackSearch(item.artistName, item.trackName)
		);
		if (data.video_id) {
			return { trackSourceId: data.video_id };
		}
	} catch {
		return null;
	}
	// no video (or quota exhausted): nothing to play here -> drop it
	return null;
}

function removeUnplayable(item: QueueItem): void {
	const index = playerStore.queue.findIndex(
		(q: QueueItem) => q.playlistTrackId === item.playlistTrackId
	);
	if (index >= 0 && index !== playerStore.currentIndex) {
		playerStore.removeFromQueue(index);
	}
}

async function hydrateOne(item: QueueItem): Promise<void> {
	const key = item.playlistTrackId!;
	if (hydrating.has(key)) return;
	hydrating.add(key);
	try {
		const patch = await resolveRadioPatch(item);
		if (patch === null) {
			removeUnplayable(item);
		} else if (Object.keys(patch).length > 0) {
			playerStore.patchQueueItemByPlaylistTrackId(key, patch);
		}
	} finally {
		hydrating.delete(key);
	}
}

async function tick(): Promise<void> {
	if (!radioSession.active) {
		stopRadioHydration();
		return;
	}
	const queue = playerStore.queue as QueueItem[];
	const from = playerStore.currentIndex;
	const window = queue.slice(from, from + 1 + LOOKAHEAD);
	await Promise.all(window.filter(needsHydration).map(hydrateOne));

	// near the end: ask the station for more
	if (queue.length - from <= EXTEND_THRESHOLD && !radioSession.atCapacity) {
		void extendRadio(ytConfiguredForSession);
	}
}

/** Reset per-session hydration state; call before pre-resolving the queue head. */
export function prepareRadioHydration(ytConfigured: boolean): void {
	stopRadioHydration();
	ytConfiguredForSession = ytConfigured;
	hydrating = new Set();
}

/** Begin the background look-ahead loop (after playback has started). */
export function startRadioHydration(): void {
	if (timer) clearInterval(timer);
	void tick();
	timer = setInterval(() => void tick(), TICK_MS);
}

export function stopRadioHydration(): void {
	if (timer) {
		clearInterval(timer);
		timer = null;
	}
}
