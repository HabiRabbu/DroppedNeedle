import type {
	AlbumBasicInfo,
	JellyfinAlbumMatch,
	JellyfinTrackInfo,
	LocalAlbumMatch,
	LocalTrackInfo,
	NavidromeAlbumMatch,
	NavidromeTrackInfo,
	PlexAlbumMatch,
	PlexTrackInfo
} from '$lib/types';
import type { QueueItem, PlaybackMeta } from '$lib/player/types';
import type { TrackMeta, TrackSourceData } from '$lib/player/queueHelpers';
import {
	buildQueueItem,
	buildQueueItemsFromJellyfin,
	buildQueueItemsFromLocal,
	buildQueueItemsFromNavidrome,
	buildQueueItemsFromPlex,
	compareDiscTrack,
	normalizeDiscNumber
} from '$lib/player/queueHelpers';
import { getCoverUrl } from '$lib/utils/errorHandling';
import { launchJellyfinPlayback } from '$lib/player/launchJellyfinPlayback';
import { launchLocalPlayback } from '$lib/player/launchLocalPlayback';
import { launchNavidromePlayback } from '$lib/player/launchNavidromePlayback';
import { launchPlexPlayback } from '$lib/player/launchPlexPlayback';
import { playerStore } from '$lib/stores/player.svelte';
import type { MenuItem } from '$lib/components/ContextMenu.svelte';
import { ListPlus, ListStart, ListMusic, Download } from 'lucide-svelte';
import { downloadFile } from '$lib/utils/downloadHelper';
import { API } from '$lib/constants';
import type { SourceCallbacks } from './albumPageState.svelte';

function getPlaybackMeta(album: AlbumBasicInfo): PlaybackMeta {
	return {
		albumId: album.musicbrainz_id,
		albumName: album.title,
		artistName: album.artist_name,
		coverUrl: getCoverUrl(album.cover_url ?? null, album.musicbrainz_id),
		artistId: album.artist_id
	};
}

function getTrackMeta(album: AlbumBasicInfo): TrackMeta {
	return {
		albumId: album.musicbrainz_id,
		albumName: album.title,
		artistName: album.artist_name,
		coverUrl: album.cover_url ?? null,
		artistId: album.artist_id
	};
}

function playSource<T extends { track_number: number; disc_number?: number | null; title: string }>(
	match: { tracks: T[] } | null,
	launcher: (tracks: T[], startIndex: number, shuffle: boolean, meta: PlaybackMeta) => void,
	album: AlbumBasicInfo,
	opts: {
		startTrack?: number;
		startDisc?: number;
		startTitle?: string;
		shuffle?: boolean;
	} = {}
): void {
	if (!match?.tracks.length) return;
	const orderedTracks = [...match.tracks].sort(compareDiscTrack);
	let idx = 0;
	if (opts.startTrack !== undefined) {
		idx = orderedTracks.findIndex(
			(t) =>
				t.track_number === opts.startTrack &&
				normalizeDiscNumber(t.disc_number) === normalizeDiscNumber(opts.startDisc)
		);
		if (idx === -1 && opts.startTitle) {
			const lower = opts.startTitle.toLowerCase();
			const titleMatcher = (t: T) => {
				const tLower = t.title.toLowerCase();
				return tLower === lower || tLower.includes(lower) || lower.includes(tLower);
			};
			if (opts.startDisc !== undefined) {
				const targetDisc = normalizeDiscNumber(opts.startDisc);
				idx = orderedTracks.findIndex(
					(t) => normalizeDiscNumber(t.disc_number) === targetDisc && titleMatcher(t)
				);
			}
			if (idx === -1) idx = orderedTracks.findIndex(titleMatcher);
		}
		if (idx === -1) return;
	}
	launcher(orderedTracks, idx, opts.shuffle ?? false, getPlaybackMeta(album));
}

export function playSourceTrack(
	source: 'jellyfin' | 'local' | 'navidrome' | 'plex',
	trackPosition: number,
	discNumber: number,
	title: string,
	album: AlbumBasicInfo,
	jellyfinMatch: JellyfinAlbumMatch | null,
	localMatch: LocalAlbumMatch | null,
	navidromeMatch: NavidromeAlbumMatch | null,
	plexMatch: PlexAlbumMatch | null
): void {
	const opts = { startTrack: trackPosition, startDisc: discNumber, startTitle: title };
	if (source === 'jellyfin') playSource(jellyfinMatch, launchJellyfinPlayback, album, opts);
	else if (source === 'local') playSource(localMatch, launchLocalPlayback, album, opts);
	else if (source === 'plex') playSource(plexMatch, launchPlexPlayback, album, opts);
	else playSource(navidromeMatch, launchNavidromePlayback, album, opts);
}

function buildTrackQueueItem(
	track: { position: number; disc_number?: number | null; title: string },
	album: AlbumBasicInfo,
	resolvedLocal: LocalTrackInfo | null,
	resolvedJellyfin: JellyfinTrackInfo | null,
	resolvedNavidrome: NavidromeTrackInfo | null = null,
	resolvedPlex: PlexTrackInfo | null = null
): QueueItem | null {
	const sourceData: TrackSourceData = {
		trackPosition: track.position,
		discNumber: normalizeDiscNumber(track.disc_number),
		trackTitle: track.title,
		trackLength:
			resolvedLocal?.duration_seconds ??
			resolvedNavidrome?.duration_seconds ??
			resolvedJellyfin?.duration_seconds ??
			resolvedPlex?.duration_seconds ??
			undefined,
		localTrack: resolvedLocal,
		navidromeTrack: resolvedNavidrome,
		jellyfinTrack: resolvedJellyfin,
		plexTrack: resolvedPlex
	};
	return buildQueueItem(getTrackMeta(album), sourceData);
}

export function getTrackContextMenuItems(
	track: { position: number; disc_number?: number | null; title: string },
	album: AlbumBasicInfo,
	resolvedLocal: LocalTrackInfo | null,
	resolvedJellyfin: JellyfinTrackInfo | null,
	resolvedNavidrome: NavidromeTrackInfo | null,
	resolvedPlex: PlexTrackInfo | null,
	playlistModalRef: { open: (tracks: QueueItem[]) => void } | null
): MenuItem[] {
	const queueItem = buildTrackQueueItem(
		track,
		album,
		resolvedLocal,
		resolvedJellyfin,
		resolvedNavidrome,
		resolvedPlex
	);
	const hasSource = queueItem !== null;
	const items: MenuItem[] = [
		{
			label: 'Add to Queue',
			icon: ListPlus,
			onclick: () => {
				if (queueItem) playerStore.addToQueue(queueItem);
			},
			disabled: !hasSource
		},
		{
			label: 'Play Next',
			icon: ListStart,
			onclick: () => {
				if (queueItem) playerStore.playNext(queueItem);
			},
			disabled: !hasSource
		},
		{
			label: 'Add to Playlist',
			icon: ListMusic,
			onclick: () => {
				if (queueItem) playlistModalRef?.open([queueItem]);
			},
			disabled: !hasSource
		}
	];
	if (resolvedLocal) {
		items.push({
			label: 'Download',
			icon: Download,
			onclick: () => downloadFile(API.download.localTrack(resolvedLocal.track_file_id))
		});
	}
	return items;
}

function getSourceQueueItems(
	source: 'jellyfin' | 'local' | 'navidrome' | 'plex',
	album: AlbumBasicInfo,
	jellyfinTracks: JellyfinTrackInfo[],
	localTracks: LocalTrackInfo[],
	navidromeTracks: NavidromeTrackInfo[],
	plexTracks: PlexTrackInfo[]
): QueueItem[] {
	const meta = getTrackMeta(album);
	if (source === 'jellyfin')
		return buildQueueItemsFromJellyfin([...jellyfinTracks].sort(compareDiscTrack), meta);
	if (source === 'navidrome')
		return buildQueueItemsFromNavidrome([...navidromeTracks].sort(compareDiscTrack), meta);
	if (source === 'plex')
		return buildQueueItemsFromPlex([...plexTracks].sort(compareDiscTrack), meta);
	return buildQueueItemsFromLocal([...localTracks].sort(compareDiscTrack), meta);
}

export function buildSourceCallbacks<
	TTrack extends { track_number: number; disc_number?: number | null; title: string },
	TMatch extends { tracks: TTrack[] } | null
>(
	matchGetter: () => TMatch,
	launcher: (
		tracks: TTrack[],
		startIndex: number | undefined,
		shuffle: boolean | undefined,
		meta: PlaybackMeta
	) => void,
	source: 'jellyfin' | 'local' | 'navidrome' | 'plex',
	albumGetter: () => AlbumBasicInfo | null,
	tracksGetters: {
		jellyfin: () => JellyfinTrackInfo[];
		local: () => LocalTrackInfo[];
		navidrome: () => NavidromeTrackInfo[];
		plex: () => PlexTrackInfo[];
	},
	playlistModalRefGetter: () => { open: (tracks: QueueItem[]) => void } | null
): SourceCallbacks {
	return {
		onPlayAll: () => {
			const a = albumGetter();
			if (a) playSource(matchGetter(), launcher, a);
		},
		onShuffle: () => {
			const a = albumGetter();
			if (a) playSource(matchGetter(), launcher, a, { shuffle: true });
		},
		onAddAllToQueue: () => {
			const a = albumGetter();
			if (!a) return;
			const items = getSourceQueueItems(
				source,
				a,
				tracksGetters.jellyfin(),
				tracksGetters.local(),
				tracksGetters.navidrome(),
				tracksGetters.plex()
			);
			if (items.length > 0) playerStore.addMultipleToQueue(items);
		},
		onPlayAllNext: () => {
			const a = albumGetter();
			if (!a) return;
			const items = getSourceQueueItems(
				source,
				a,
				tracksGetters.jellyfin(),
				tracksGetters.local(),
				tracksGetters.navidrome(),
				tracksGetters.plex()
			);
			if (items.length > 0) playerStore.playMultipleNext(items);
		},
		onAddAllToPlaylist: () => {
			const a = albumGetter();
			if (!a) return;
			const items = getSourceQueueItems(
				source,
				a,
				tracksGetters.jellyfin(),
				tracksGetters.local(),
				tracksGetters.navidrome(),
				tracksGetters.plex()
			);
			if (items.length > 0) playlistModalRefGetter()?.open(items);
		}
	};
}
