import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

// keep the Request button real; stub only its mutation hook so it renders without a QueryClient
vi.mock('$lib/queries/downloads/DownloadMutations.svelte', () => ({
	requestTrack: () => ({ mutate: vi.fn(), isPending: false })
}));

// download_client gates the Request button
vi.mock('$lib/stores/integration', () => ({
	integrationStore: {
		subscribe: (cb: (v: unknown) => void) => {
			cb({ download_client: true });
			return () => {};
		}
	}
}));

vi.mock('$lib/stores/player.svelte', () => ({
	playerStore: { isPlaying: false, nowPlaying: null, currentQueueItem: null }
}));

// heavy / QueryClient-dependent children not under test
const { emptyComponent } = vi.hoisted(() => ({
	emptyComponent: () => {
		const Comp = function () {};
		Comp.prototype = {};
		return { default: Comp };
	}
}));
vi.mock('$lib/components/NowPlayingIndicator.svelte', emptyComponent);
vi.mock('$lib/components/TrackPlayButton.svelte', emptyComponent);
vi.mock('$lib/components/TrackPreviewButton.svelte', emptyComponent);
vi.mock('$lib/components/TrackSourceButton.svelte', emptyComponent);
vi.mock('$lib/components/ContextMenu.svelte', emptyComponent);
vi.mock('$lib/components/JellyfinIcon.svelte', emptyComponent);
vi.mock('$lib/components/LocalFilesIcon.svelte', emptyComponent);
vi.mock('$lib/components/NavidromeIcon.svelte', emptyComponent);
vi.mock('$lib/components/PlexIcon.svelte', emptyComponent);
vi.mock('$lib/components/library/LibraryTrackRow.svelte', emptyComponent);

import AlbumTrackList from './AlbumTrackList.svelte';
import { buildRenderedTrackSections } from './albumTrackResolvers';
import type { LibraryFileMeta } from '$lib/types';

const TRACKS = [
	{ position: 1, disc_number: 1, title: 'Matched By MBID', length: 100000, recording_id: 'rec-1' },
	{
		position: 2,
		disc_number: 1,
		title: 'Matched By Position',
		length: 100000,
		recording_id: 'rec-2'
	},
	{ position: 3, disc_number: 1, title: 'Genuinely Missing', length: 100000, recording_id: 'rec-3' }
];

function libTrack(over: Partial<LibraryFileMeta>): LibraryFileMeta {
	return {
		id: 'f',
		recording_mbid: null,
		disc_number: 1,
		track_number: 0,
		track_title: '',
		artist_name: 'Artist',
		file_path: '/x.flac',
		file_format: 'flac',
		bit_rate: null,
		sample_rate: null,
		bit_depth: null,
		duration_seconds: null,
		file_size_bytes: 1,
		...over
	};
}

// rec-1 present by recording MBID; track 1:2 present by position only (NULL MBID)
const byRecording = new Map<string, LibraryFileMeta>([
	['rec-1', libTrack({ id: 'a', recording_mbid: 'rec-1', track_number: 1 })]
]);
const byPosition = new Map<string, LibraryFileMeta>([
	['1:1', libTrack({ id: 'a', recording_mbid: 'rec-1', track_number: 1 })],
	['1:2', libTrack({ id: 'b', recording_mbid: null, track_number: 2 })]
]);

function renderList() {
	const album = {
		musicbrainz_id: 'rg-1',
		artist_name: 'Artist',
		title: 'Album',
		cover_url: null,
		artist_id: 'art-1'
	};
	const props = {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any -- minimal album stub for the test
		album: album as any,
		renderedTrackSections: buildRenderedTrackSections(
			// eslint-disable-next-line @typescript-eslint/no-explicit-any -- minimal MB track stubs
			TRACKS as any
		),
		trackLinkMap: new Map(),
		jellyfinMatch: null,
		localMatch: null,
		navidromeMatch: null,
		plexMatch: null,
		jellyfinTrackMap: new Map(),
		localTrackMap: new Map(),
		navidromeTrackMap: new Map(),
		plexTrackMap: new Map(),
		jellyfinTracks: [],
		localTracks: [],
		navidromeTracks: [],
		plexTracks: [],
		trackLinks: [],
		youtubeEnabled: false,
		youtubeApiConfigured: false,
		previewCacheMap: new Map(),
		jellyfinEnabled: false,
		localfilesEnabled: false,
		navidromeEnabled: false,
		plexEnabled: false,
		libraryTracksByRecording: byRecording,
		libraryTracksByPosition: byPosition,
		releaseGroupMbid: 'rg-1',
		onPlaySourceTrack: vi.fn(),
		onTrackGenerated: vi.fn(),
		onQuotaUpdate: vi.fn(),
		getTrackContextMenuItems: () => []
	};
	render(AlbumTrackList, { props } as unknown as Parameters<
		typeof render<typeof AlbumTrackList>
	>[1]);
}

describe('AlbumTrackList in-library detection', () => {
	it('shows the Request button only for the genuinely-missing track', async () => {
		expect.assertions(2);
		renderList();

		// matched rows are hidden, leaving exactly one Request button for the genuinely missing track
		await expect.element(page.getByText('Genuinely Missing')).toBeVisible();
		const requestButtons = page.getByRole('button', { name: 'Request this track' }).elements();
		expect(requestButtons).toHaveLength(1);
	});
});
