import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';
import { toastStore } from '$lib/stores/toast';
import type {
	CancelDownloadResponse,
	ReimportDownloadResponse,
	RequestAccepted,
	RetryDownloadResponse,
	TrackRequestResponse
} from '$lib/types';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

interface AlbumRequestInput {
	release_group_mbid: string;
	artist_name: string;
	album_title: string;
	year?: number | null;
	artist_mbid?: string | null;
}

interface TrackRequestInput {
	recording_mbid: string;
	artist_name: string;
	track_title: string;
	album_title?: string | null;
	duration_seconds?: number | null;
	release_group_mbid?: string | null;
	artist_mbid?: string | null;
}

const invalidateTasks = () =>
	invalidateQueriesWithPersister({ queryKey: DownloadQueryKeyFactory.tasks() });

function errorMessage(err: unknown, fallback: string): string {
	return err instanceof Error && err.message ? err.message : fallback;
}

// UX-2: one toast at click time; the async search outcome surfaces later via the task's live status in /downloads
export function requestAlbum() {
	return createMutation(() => ({
		mutationFn: (input: AlbumRequestInput) =>
			api.global.post<RequestAccepted>(API.requests.new(), {
				musicbrainz_id: input.release_group_mbid,
				artist: input.artist_name,
				album: input.album_title,
				year: input.year ?? null,
				artist_mbid: input.artist_mbid ?? null
			}),
		onSuccess: (data: RequestAccepted) => {
			toastStore.show({
				message:
					data.status === 'awaiting_approval'
						? 'Request submitted for admin approval'
						: 'Request submitted - searching for downloads',
				type: 'success'
			});
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Request failed'), type: 'error' })
	}));
}

export function requestTrack() {
	return createMutation(() => ({
		mutationFn: (input: TrackRequestInput) =>
			api.global.post<TrackRequestResponse>(API.tracks.request(input.recording_mbid), {
				artist_name: input.artist_name,
				track_title: input.track_title,
				album_title: input.album_title ?? null,
				duration_seconds: input.duration_seconds ?? null,
				release_group_mbid: input.release_group_mbid ?? null,
				artist_mbid: input.artist_mbid ?? null
			}),
		onSuccess: (data: TrackRequestResponse) => {
			toastStore.show({
				message:
					data.status === 'already_in_library'
						? 'That track is already in your library'
						: 'Track requested - searching for downloads',
				type: 'success'
			});
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Track request failed'), type: 'error' })
	}));
}

export function cancelDownload() {
	return createMutation(() => ({
		mutationFn: (id: string) =>
			api.global.post<CancelDownloadResponse>(API.downloads.cancel(id), {}),
		onSuccess: () => {
			toastStore.show({ message: 'Download cancelled', type: 'info' });
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to cancel download'), type: 'error' })
	}));
}

// Stop a scheduled auto-retry. Cancelling the failed/partial task drops it out of the
// retry sweep (status -> cancelled); a manual Retry is still available afterwards.
export function stopAutoRetry() {
	return createMutation(() => ({
		mutationFn: (id: string) =>
			api.global.post<CancelDownloadResponse>(API.downloads.cancel(id), {}),
		onSuccess: () => {
			toastStore.show({ message: 'Stopped retrying', type: 'info' });
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to stop retrying'), type: 'error' })
	}));
}

export function retryDownload() {
	return createMutation(() => ({
		mutationFn: (id: string) => api.global.post<RetryDownloadResponse>(API.downloads.retry(id), {}),
		onSuccess: () => {
			toastStore.show({ message: 'Download retry initiated', type: 'info' });
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to retry download'), type: 'error' })
	}));
}

// Bulk queue actions for the dashboard. Each reports how many rows it touched so the
// toast is honest ("Cleared 12 downloads", "Nothing to clear").
function pluralDownloads(n: number): string {
	return `${n} download${n === 1 ? '' : 's'}`;
}

export function clearFinished() {
	return createMutation(() => ({
		mutationFn: () => api.global.post<{ cleared: number }>(API.downloads.clear(), {}),
		onSuccess: (data: { cleared: number }) => {
			toastStore.show({
				message: data.cleared > 0 ? `Cleared ${pluralDownloads(data.cleared)}` : 'Nothing to clear',
				type: 'info'
			});
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to clear downloads'), type: 'error' })
	}));
}

export function stopAllRetries() {
	return createMutation(() => ({
		mutationFn: () => api.global.post<{ stopped: number }>(API.downloads.stopAllRetries(), {}),
		onSuccess: (data: { stopped: number }) => {
			toastStore.show({
				message:
					data.stopped > 0
						? `Stopped retrying ${pluralDownloads(data.stopped)}`
						: 'No retries to stop',
				type: 'info'
			});
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to stop retries'), type: 'error' })
	}));
}

export function retryAllFailed() {
	return createMutation(() => ({
		mutationFn: () => api.global.post<{ retried: number }>(API.downloads.retryAllFailed(), {}),
		onSuccess: (data: { retried: number }) => {
			toastStore.show({
				message:
					data.retried > 0 ? `Retrying ${pluralDownloads(data.retried)}` : 'Nothing to retry',
				type: 'info'
			});
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to retry downloads'), type: 'error' })
	}));
}

// Held-track review actions. Both refresh the held list + the queue (invalidateTasks covers
// the held query, nested under the tasks key); import also refreshes the album's library
// status so the newly-placed track shows on the album page.
interface HeldActionInput {
	id: number;
	release_group_mbid?: string | null;
}

function invalidateAlbum(releaseGroupMbid?: string | null) {
	if (releaseGroupMbid) {
		void invalidateQueriesWithPersister({
			queryKey: LibraryQueryKeyFactory.album(releaseGroupMbid)
		});
	}
}

export function importHeldTrack() {
	return createMutation(() => ({
		mutationFn: (input: HeldActionInput) =>
			api.global.post<{ status: string; final_path: string | null }>(
				API.downloads.heldImport(input.id),
				{}
			),
		onSuccess: (_data: { status: string }, input: HeldActionInput) => {
			toastStore.show({ message: 'Imported', type: 'success' });
			void invalidateTasks();
			invalidateAlbum(input.release_group_mbid);
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to import track'), type: 'error' })
	}));
}

export function discardHeldTrack() {
	return createMutation(() => ({
		mutationFn: (input: HeldActionInput) =>
			api.global.post<{ status: string }>(API.downloads.heldDiscard(input.id), {}),
		onSuccess: () => {
			toastStore.show({ message: 'Discarded', type: 'info' });
			void invalidateTasks();
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to discard track'), type: 'error' })
	}));
}

interface ReimportInput {
	id: string;
	release_group_mbid?: string | null;
}

export function reimportDownload() {
	return createMutation(() => ({
		mutationFn: (input: ReimportInput) =>
			api.global.post<ReimportDownloadResponse>(API.downloads.reimport(input.id), {}),
		onSuccess: (data: ReimportDownloadResponse, input: ReimportInput) => {
			if (data.status === 'completed') {
				toastStore.show({ message: 'Import complete', type: 'success' });
			} else if (data.status === 'partial') {
				toastStore.show({
					message: 'Imported what was found, some files still missing',
					type: 'info'
				});
			} else {
				toastStore.show({
					message: data.error_message ?? "Couldn't find the files on the downloads mount yet",
					type: 'error'
				});
			}
			void invalidateTasks();
			// A completed/partial reimport writes files into the library; refresh the album
			// so its page/badge don't show stale data (the persister survives reloads).
			if (data.status === 'completed' || data.status === 'partial') {
				invalidateAlbum(input.release_group_mbid);
			}
		},
		onError: (err: unknown) =>
			toastStore.show({ message: errorMessage(err, 'Failed to reimport download'), type: 'error' })
	}));
}
