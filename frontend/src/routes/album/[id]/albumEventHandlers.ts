import { goto } from '$app/navigation';
import { artistHref } from '$lib/utils/entityRoutes';
import type { AlbumBasicInfo, YouTubeTrackLink, YouTubeLink, YouTubeQuotaStatus } from '$lib/types';
import { compareDiscTrack, getDiscTrackKey } from '$lib/player/queueHelpers';
import { requestAlbum } from '$lib/utils/albumRequest';

export interface EventHandlerDeps {
	getAlbum: () => AlbumBasicInfo | null;
	setAlbum: (a: AlbumBasicInfo | null) => void;
	getAlbumId: () => string;
	albumBasicCacheSet: (data: AlbumBasicInfo, key: string) => void;
	setTrackLinks: (tl: YouTubeTrackLink[]) => void;
	getTrackLinks: () => YouTubeTrackLink[];
	setAlbumLink: (l: YouTubeLink) => void;
	setQuota: (q: YouTubeQuotaStatus) => void;
	setRequesting: (v: boolean) => void;
	getRequesting: () => boolean;
	setShowDeleteModal: (v: boolean) => void;
	setShowArtistRemovedModal: (v: boolean) => void;
	setRemovedArtistName: (v: string) => void;
	setToast: (msg: string, type: 'success' | 'error' | 'info' | 'warning') => void;
	setShowToast: (v: boolean) => void;
	onRequestSuccess?: () => void;
}

export function createEventHandlers(deps: EventHandlerDeps) {
	function handleTrackGenerated(link: YouTubeTrackLink): void {
		const linkKey = getDiscTrackKey(link);
		deps.setTrackLinks(
			[...deps.getTrackLinks().filter((tl) => getDiscTrackKey(tl) !== linkKey), link].sort(
				compareDiscTrack
			)
		);
	}

	function handleTrackLinksUpdate(links: YouTubeTrackLink[]): void {
		deps.setTrackLinks([...links].sort(compareDiscTrack));
	}

	function handleAlbumLinkUpdate(link: YouTubeLink): void {
		deps.setAlbumLink(link);
	}

	function handleQuotaUpdate(q: YouTubeQuotaStatus): void {
		deps.setQuota(q);
	}

	async function handleRequest(): Promise<void> {
		const album = deps.getAlbum();
		if (!album || deps.getRequesting()) return;
		deps.setRequesting(true);
		try {
			const result = await requestAlbum(album.musicbrainz_id, {
				artist: album.artist_name ?? undefined,
				album: album.title,
				year: album.year ?? undefined,
				artistMbid: album.artist_id
			});
			const current = deps.getAlbum();
			if (result.success && current) {
				current.requested = true;
				deps.setAlbum(current);
				deps.albumBasicCacheSet(current, deps.getAlbumId());
				deps.setToast('Added to Library', 'success');
				deps.setShowToast(true);
				deps.onRequestSuccess?.();
			}
		} finally {
			deps.setRequesting(false);
		}
	}

	function handleDeleteClick(): void {
		deps.setShowDeleteModal(true);
	}

	function handleDeleted(result: { artist_removed: boolean; artist_name?: string | null }): void {
		deps.setShowDeleteModal(false);
		const album = deps.getAlbum();
		if (album) {
			album.in_library = false;
			album.requested = false;
			deps.setAlbum(album);
			deps.albumBasicCacheSet(album, deps.getAlbumId());
		}
		deps.setToast('Removed from Library', 'success');
		deps.setShowToast(true);
		if (result.artist_removed && result.artist_name) {
			deps.setRemovedArtistName(result.artist_name);
			deps.setShowArtistRemovedModal(true);
		}
	}

	function goToArtist(): void {
		const album = deps.getAlbum();
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- artistHref uses resolve() internally
		if (album?.artist_id) goto(artistHref(album.artist_id));
	}

	return {
		handleTrackGenerated,
		handleTrackLinksUpdate,
		handleAlbumLinkUpdate,
		handleQuotaUpdate,
		handleRequest,
		handleDeleteClick,
		handleDeleted,
		goToArtist
	};
}
