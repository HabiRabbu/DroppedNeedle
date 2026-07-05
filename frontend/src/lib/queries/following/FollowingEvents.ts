import { API } from '$lib/constants';
import { toastStore } from '$lib/stores/toast';
import { authStore } from '$lib/stores/authStore.svelte';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { PlaylistQueryKeyFactory } from '$lib/queries/playlists/PlaylistQueryKeyFactory';

// SSEPublisher replays its last payload to every new subscriber, so
// auto_download_enqueued arrives again on each reconnect. De-dupe by task id
// (per session) so each enqueue toasts at most once.
const SEEN_KEY = 'msr:auto_download_toasts';

function loadSeen(): Set<string> {
	try {
		const raw = sessionStorage.getItem(SEEN_KEY);
		return new Set(raw ? (JSON.parse(raw) as string[]) : []);
	} catch {
		return new Set();
	}
}

function persistSeen(seen: Set<string>): void {
	try {
		const ids = [...seen].slice(-100);
		sessionStorage.setItem(SEEN_KEY, JSON.stringify(ids));
	} catch {
		// sessionStorage unavailable - de-dupe stays in-memory only
	}
}

export function createFollowingEvents() {
	let source: EventSource | null = null;
	let seen = new Set<string>();
	// Spotify import completions replay on reconnect too; de-dupe by event_id so the
	// playlist queries are invalidated once per real import (in-memory is enough - a
	// redundant invalidation is idempotent, unlike a repeated toast).
	let importsSeen = new Set<string>();

	function handlePlaylistImported(event: Event): void {
		let data: Record<string, unknown>;
		try {
			data = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
		} catch {
			return;
		}
		const playlistId = typeof data.playlist_id === 'string' ? data.playlist_id : '';
		const eventId = typeof data.event_id === 'string' ? data.event_id : '';
		if (!playlistId || (eventId && importsSeen.has(eventId))) return;
		if (eventId) importsSeen.add(eventId);
		// import finished populating - refresh the open detail view and the list count
		const userId = authStore.user?.id;
		void invalidateQueriesWithPersister({
			queryKey: PlaylistQueryKeyFactory.detail(userId, playlistId)
		});
		void invalidateQueriesWithPersister({ queryKey: PlaylistQueryKeyFactory.list(userId) });
	}

	function handleEnqueued(event: Event): void {
		let data: Record<string, unknown>;
		try {
			data = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
		} catch {
			return;
		}
		const taskId = typeof data.task_id === 'string' ? data.task_id : '';
		if (!taskId || seen.has(taskId)) return;
		seen.add(taskId);
		persistSeen(seen);
		const title = typeof data.title === 'string' && data.title ? data.title : 'a new release';
		toastStore.show({ message: `Auto-downloading new release: ${title}`, type: 'info' });
	}

	function start(): void {
		stop();
		seen = loadSeen();
		importsSeen = new Set();
		source = new EventSource(API.following.events());
		source.addEventListener('auto_download_enqueued', handleEnqueued);
		source.addEventListener('playlist_imported', handlePlaylistImported);
	}

	function stop(): void {
		if (source) {
			source.close();
			source = null;
		}
	}

	return { start, stop };
}
