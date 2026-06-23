import { errorModal } from '$lib/stores/errorModal';
import { libraryStore } from '$lib/stores/library';
import { api, ApiError } from '$lib/api/client';

export type AlbumRequestResult = {
	success: boolean;
	error?: string;
};

export type AlbumRequestContext = {
	artist?: string;
	album?: string;
	year?: number | null;
	artistMbid?: string;
	monitorArtist?: boolean;
	autoDownloadArtist?: boolean;
};

export type BatchAlbumItem = {
	musicbrainz_id: string;
	artist_name?: string;
	album_title?: string;
	year?: number | null;
	artist_mbid?: string;
};

export type BatchRequestResult = {
	success: boolean;
	requested: number;
	skipped: number;
	overflow: number;
	error?: string;
};

export async function requestBatch(
	items: BatchAlbumItem[],
	options?: { monitorArtist?: boolean; autoDownloadArtist?: boolean }
): Promise<BatchRequestResult> {
	try {
		const response = await api.global.post<{
			success: boolean;
			message: string;
			requested: number;
			skipped: number;
			overflow: number;
		}>('/api/v1/requests/batch', {
			items,
			monitor_artist: options?.monitorArtist ?? false,
			auto_download_artist: options?.autoDownloadArtist ?? false
		});

		for (const item of items) {
			libraryStore.addRequested(item.musicbrainz_id);
		}

		return {
			success: response.success,
			requested: response.requested,
			skipped: response.skipped,
			overflow: response.overflow
		};
	} catch (e) {
		if (e instanceof ApiError) {
			const errorDetail = e.message || 'Unknown error';
			errorModal.show('Batch Request Failed', errorDetail, '');
			return { success: false, requested: 0, skipped: 0, overflow: 0, error: errorDetail };
		}
		errorModal.show('Batch Request Failed', 'Network error occurred', '');
		return {
			success: false,
			requested: 0,
			skipped: 0,
			overflow: 0,
			error: 'Network error occurred'
		};
	}
}

export async function requestAlbum(
	musicbrainzId: string,
	context?: AlbumRequestContext
): Promise<AlbumRequestResult> {
	try {
		await api.global.post('/api/v1/requests/new', {
			musicbrainz_id: musicbrainzId,
			artist: context?.artist ?? undefined,
			album: context?.album ?? undefined,
			year: context?.year ?? undefined,
			artist_mbid: context?.artistMbid ?? undefined,
			monitor_artist: context?.monitorArtist ?? false,
			auto_download_artist: context?.autoDownloadArtist ?? false
		});

		libraryStore.addRequested(musicbrainzId);
		return { success: true };
	} catch (e) {
		if (e instanceof ApiError) {
			const errorDetail = e.message || 'Unknown error';
			errorModal.show('Request Failed', errorDetail, '');

			return { success: false, error: errorDetail };
		}
		errorModal.show('Request Failed', 'Network error occurred', '');
		return { success: false, error: 'Network error occurred' };
	}
}
