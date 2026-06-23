import { nowPlayingStore } from '$lib/stores/nowPlayingSessions.svelte';
import { playerStore } from '$lib/stores/player.svelte';
import { authStore } from '$lib/stores/authStore.svelte';
import type { NowPlayingSession } from '$lib/types';
import { SvelteMap } from 'svelte/reactivity';

type SourceKey = 'jellyfin' | 'navidrome' | 'plex';

const GRACE_MS: Record<SourceKey, number> = {
	jellyfin: 30_000,
	navidrome: 180_000,
	plex: 30_000
};

type OwnedEntry = { track: string; idleSince: number };

function buildLocalSession(): NowPlayingSession | null {
	const state = playerStore.playbackState;
	if (state === 'idle' || state === 'error') return null;
	const np = playerStore.nowPlaying;
	if (!np) return null;

	const src = np.sourceType;
	if (src !== 'jellyfin' && src !== 'navidrome' && src !== 'plex') return null;

	return {
		id: `local-${src}-${np.trackSourceId ?? np.albumId}`,
		user_name: authStore.user?.display_name ?? '',
		track_name: np.trackName ?? '',
		artist_name: np.artistName,
		album_name: np.albumName,
		cover_url: np.coverUrl ?? '',
		device_name: 'DroppedNeedle',
		is_paused: state === 'paused' || state === 'buffering' || state === 'loading',
		source: src,
		progress_ms: playerStore.progress * 1000,
		duration_ms: playerStore.duration * 1000,
		_isLocal: true
	};
}

const ownedSessions = new SvelteMap<SourceKey, OwnedEntry>();
let currentOwnedSource: SourceKey | null = null;

function createMergedStore() {
	const mergedSessions = $derived.by(() => {
		const local = buildLocalSession();
		const server = nowPlayingStore.sessions;

		if (local) {
			const src = local.source as SourceKey;
			if (currentOwnedSource && currentOwnedSource !== src) {
				const prev = ownedSessions.get(currentOwnedSource);
				if (prev && !prev.idleSince) {
					ownedSessions.set(currentOwnedSource, { ...prev, idleSince: Date.now() });
				}
			}
			currentOwnedSource = src;
			ownedSessions.set(src, { track: local.track_name, idleSince: 0 });
		} else if (currentOwnedSource) {
			const entry = ownedSessions.get(currentOwnedSource);
			if (entry && !entry.idleSince) {
				ownedSessions.set(currentOwnedSource, { ...entry, idleSince: Date.now() });
			}
			currentOwnedSource = null;
		}

		const now = Date.now();

		for (const [src, entry] of ownedSessions) {
			if (entry.idleSince && now - entry.idleSince >= GRACE_MS[src]) {
				ownedSessions.delete(src);
			}
		}

		if (!local) {
			const hasGraceEntries = ownedSessions.size > 0;
			if (hasGraceEntries) {
				return server.filter((s) => {
					const src = s.source as SourceKey;
					const owned = ownedSessions.get(src);
					if (owned && owned.idleSince && s.track_name === owned.track) return false;
					return true;
				});
			}
			return server;
		}

		const localSource = local.source as SourceKey;
		const filtered = server.filter((s) => {
			if (s.source === localSource && s.track_name === local.track_name) return false;
			const src = s.source as SourceKey;
			const owned = ownedSessions.get(src);
			if (owned && owned.idleSince && s.track_name === owned.track) return false;
			return true;
		});
		return [local, ...filtered];
	});

	const activeSessions = $derived(mergedSessions.filter((s) => !s.is_paused));
	const primarySession = $derived(activeSessions[0] ?? mergedSessions[0] ?? null);

	function isSourcePlaying(source: SourceKey): boolean {
		return mergedSessions.some((s) => s.source === source && !s.is_paused);
	}

	function sourceHasSessions(source: SourceKey): boolean {
		return mergedSessions.some((s) => s.source === source);
	}

	function sessionsForSource(source: SourceKey): NowPlayingSession[] {
		return mergedSessions.filter((s) => s.source === source);
	}

	return {
		get sessions() {
			return mergedSessions;
		},
		get activeSessions() {
			return activeSessions;
		},
		get primarySession() {
			return primarySession;
		},
		isSourcePlaying,
		sourceHasSessions,
		sessionsForSource,
		start: nowPlayingStore.start,
		stop: nowPlayingStore.stop,
		refresh: nowPlayingStore.refresh
	};
}

export const nowPlayingMerged = createMergedStore();
