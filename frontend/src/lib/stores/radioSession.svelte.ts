/**
 * Live radio session state: remembers the seed and what already played so the
 * station can extend itself near the end of the queue (exclusions prevent repeats).
 */
import { SvelteSet } from 'svelte/reactivity';
import type { RadioPlanRequest } from '$lib/types';

const MAX_SESSION_TRACKS = 150;

function createRadioSession() {
	let active = $state(false);
	let title = $state('');
	let seed = $state<Omit<RadioPlanRequest, 'exclude_recording_mbids' | 'fast'> | null>(null);
	let queuedRecordingMbids = $state<string[]>([]);
	const queuedTrackKeys = new SvelteSet<string>();
	let extending = $state(false);

	return {
		get active() {
			return active;
		},
		get title() {
			return title;
		},
		get seed() {
			return seed;
		},
		get extending() {
			return extending;
		},
		set extending(v: boolean) {
			extending = v;
		},
		get exclusions() {
			return queuedRecordingMbids;
		},
		get trackCount() {
			return queuedTrackKeys.size;
		},
		get atCapacity() {
			return queuedTrackKeys.size >= MAX_SESSION_TRACKS;
		},

		start(
			sessionTitle: string,
			sessionSeed: Omit<RadioPlanRequest, 'exclude_recording_mbids' | 'fast'>
		) {
			active = true;
			title = sessionTitle;
			seed = sessionSeed;
			queuedRecordingMbids = [];
			queuedTrackKeys.clear();
			extending = false;
		},

		/** Record queued tracks; returns only the ones not already in the session. */
		claim(tracks: { artist_name: string; track_name: string; recording_mbid?: string | null }[]) {
			const fresh: typeof tracks = [];
			const nextMbids = [...queuedRecordingMbids];
			for (const t of tracks) {
				const key = `${t.artist_name.toLowerCase()}|${t.track_name.toLowerCase()}`;
				if (queuedTrackKeys.has(key)) continue;
				queuedTrackKeys.add(key);
				if (t.recording_mbid) nextMbids.push(t.recording_mbid);
				fresh.push(t);
			}
			queuedRecordingMbids = nextMbids;
			return fresh;
		},

		end() {
			active = false;
			title = '';
			seed = null;
			queuedRecordingMbids = [];
			queuedTrackKeys.clear();
			extending = false;
		}
	};
}

export const radioSession = createRadioSession();
