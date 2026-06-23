import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';
import type {
	CancelDownloadResponse,
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
				release_group_mbid: input.release_group_mbid ?? null
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
