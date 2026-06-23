import { libraryStore } from '$lib/stores/library';
import { API } from '$lib/constants';
import { api } from '$lib/api/client';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { LibraryQueryKeyFactory } from '$lib/queries/library/LibraryQueryKeyFactory';
import { ArtistQueryKeyFactory } from '$lib/queries/artist/ArtistQueryKeyFactory';
import { HomeQueryKeyFactory } from '$lib/queries/HomeQueryKeyFactory';
import { DiscoverQueryKeyFactory } from '$lib/queries/discover/DiscoverQueryKeyFactory';

export interface AlbumRemoveResult {
	success: boolean;
	artist_removed: boolean;
	artist_name?: string | null;
	error?: string;
}

export interface AlbumRemovePreviewResult {
	success: boolean;
	artist_will_be_removed: boolean;
	artist_name?: string | null;
	error?: string;
}

export async function getAlbumRemovePreview(
	musicbrainzId: string
): Promise<AlbumRemovePreviewResult> {
	try {
		const data = await api.global.get<{
			artist_will_be_removed?: boolean;
			artist_name?: string | null;
		}>(API.library.removeAlbumPreview(musicbrainzId));
		return {
			success: true,
			artist_will_be_removed: data.artist_will_be_removed ?? false,
			artist_name: data.artist_name ?? null
		};
	} catch (e) {
		return {
			success: false,
			artist_will_be_removed: false,
			error: e instanceof Error ? e.message : 'Unknown error'
		};
	}
}

export async function removeAlbum(
	musicbrainzId: string,
	deleteFiles: boolean = false
): Promise<AlbumRemoveResult> {
	try {
		const url = `${API.library.removeAlbum(musicbrainzId)}?delete_files=${deleteFiles}`;
		const data = await api.global.delete<{
			artist_removed?: boolean;
			artist_name?: string | null;
		}>(url);
		libraryStore.removeMbid(musicbrainzId);
		// The cached album library-status query (which gates the re-download button)
		// and the library lists/stats all live under the 'library' key. A prefix
		// invalidation refetches them so removal reflects immediately with no manual
		// re-scan - and covers the per-album status key, since '.all' is its prefix.
		await invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all });
		// Artist pages show each release's "In Library" badge from the cached
		// ['artist', id, 'releases'] query, which lives outside the 'library' key.
		// Refetch the artist tree so a removed album stops showing as in-library there.
		await invalidateQueriesWithPersister({ queryKey: ArtistQueryKeyFactory.prefix });
		// Home and Discover album cards carry a cached in_library flag too, so refresh
		// those trees as well (search/genre read libraryStore reactively, handled above).
		await invalidateQueriesWithPersister({ queryKey: HomeQueryKeyFactory.prefix });
		await invalidateQueriesWithPersister({ queryKey: DiscoverQueryKeyFactory.prefix });
		return {
			success: true,
			artist_removed: data?.artist_removed ?? false,
			artist_name: data?.artist_name ?? null
		};
	} catch (e) {
		return {
			success: false,
			artist_removed: false,
			error: e instanceof Error ? e.message : 'Unknown error'
		};
	}
}
