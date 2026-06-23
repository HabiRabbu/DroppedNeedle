import type { QueueItem } from '$lib/player/types';
import { isPlexScrobbleEnabled } from '$lib/player/plexPlaybackApi';

interface ProgressReporterState {
	jellyfinItem: QueueItem | null;
	progress: number;
	isPaused: boolean;
}

type ReportProgressFn = (
	trackSourceId: string,
	playSessionId: string,
	progress: number,
	isPaused: boolean
) => Promise<boolean>;

export function createProgressReporter(
	reportProgress: ReportProgressFn,
	intervalMs: number,
	maxFailures: number
) {
	let interval: ReturnType<typeof setInterval> | null = null;
	let consecutiveFailures = 0;

	function start(getState: () => ProgressReporterState): void {
		stop();
		const item = getState().jellyfinItem;
		if (!item?.playSessionId) return;

		interval = setInterval(async () => {
			const { jellyfinItem, progress, isPaused } = getState();
			if (!jellyfinItem?.playSessionId) {
				stop();
				return;
			}
			try {
				const ok = await reportProgress(
					jellyfinItem.trackSourceId,
					jellyfinItem.playSessionId,
					progress,
					isPaused
				);
				if (ok) {
					consecutiveFailures = 0;
					return;
				}
				consecutiveFailures += 1;
				if (consecutiveFailures >= maxFailures) stop();
			} catch {
				// Ignore errors
			}
		}, intervalMs);
	}

	function stop(): void {
		if (interval) {
			clearInterval(interval);
			interval = null;
		}
		consecutiveFailures = 0;
	}

	return { start, stop };
}

function buildStopSessionPayload(
	playSessionId: string,
	positionSeconds: number
): { play_session_id: string; position_seconds: number } {
	return { play_session_id: playSessionId, position_seconds: positionSeconds };
}

export function createBeforeUnloadHandler(
	getState: () => {
		jellyfinItem: QueueItem | null;
		currentItem: QueueItem | null;
		progress: number;
	},
	jellyfinStopUrl: (trackSourceId: string) => string,
	navidromeScrobbleUrl: (trackSourceId: string) => string,
	plexScrobbleUrl: (ratingKey: string) => string
): () => void {
	return () => {
		if (typeof navigator === 'undefined' || typeof navigator.sendBeacon !== 'function') return;
		const { jellyfinItem, currentItem, progress } = getState();

		if (jellyfinItem?.playSessionId) {
			const payload = new Blob(
				[JSON.stringify(buildStopSessionPayload(jellyfinItem.playSessionId, progress))],
				{ type: 'application/json' }
			);
			navigator.sendBeacon(jellyfinStopUrl(jellyfinItem.trackSourceId), payload);
		}

		if (currentItem?.sourceType === 'navidrome' && progress > 30) {
			navigator.sendBeacon(
				navidromeScrobbleUrl(currentItem.trackSourceId),
				new Blob([], { type: 'application/json' })
			);
		}

		if (
			currentItem?.sourceType === 'plex' &&
			currentItem.plexRatingKey &&
			progress > 30 &&
			isPlexScrobbleEnabled()
		) {
			navigator.sendBeacon(
				plexScrobbleUrl(currentItem.plexRatingKey),
				new Blob([], { type: 'application/json' })
			);
		}
	};
}
