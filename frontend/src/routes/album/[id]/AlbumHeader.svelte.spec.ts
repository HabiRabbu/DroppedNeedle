import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import type { AlbumBasicInfo, AlbumEditionsResponse, AlbumTracksInfo } from '$lib/types';

const h = vi.hoisted(() => ({
	editions: undefined as AlbumEditionsResponse | undefined,
	setPin: vi.fn(),
	clearPin: vi.fn(),
	acquire: vi.fn()
}));

vi.mock('$lib/queries/albums/EditionQueries.svelte', () => ({
	getAlbumEditionsQuery: () => ({
		get data() {
			return h.editions;
		}
	}),
	setEditionPin: () => ({ mutateAsync: h.setPin, isPending: false }),
	clearEditionPin: () => ({ mutateAsync: h.clearPin, isPending: false }),
	acquireEdition: () => ({ mutateAsync: h.acquire, isPending: false })
}));

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	rescanAlbum: () => ({ mutateAsync: vi.fn(), isPending: false })
}));

vi.mock('$lib/queries/downloads/UpgradeQueries.svelte', () => ({
	requestUpgradeAlbum: () => ({ mutateAsync: vi.fn(), isPending: false })
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { isAdmin: true, isTrusted: true }
}));

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

vi.mock('$lib/stores/deckSampler.svelte', () => ({
	deckSampler: { activeKey: null, status: 'idle', start: vi.fn(), stop: vi.fn() }
}));

const { emptyComponent } = vi.hoisted(() => ({
	emptyComponent: () => {
		const Comp = function () {};
		Comp.prototype = {};
		return { default: Comp };
	}
}));
vi.mock('$lib/components/AlbumImage.svelte', emptyComponent);
vi.mock('$lib/components/HeroBackdrop.svelte', emptyComponent);
vi.mock('$lib/components/downloads/AlbumDownloadStatus.svelte', emptyComponent);

import AlbumHeader from './AlbumHeader.svelte';

const album: AlbumBasicInfo = {
	title: 'Avalon',
	musicbrainz_id: '4b6276da-e7c7-36df-8771-34b92f774d3b',
	artist_name: 'Juliet',
	artist_id: 'artist-1',
	year: 2008,
	in_library: true
};

const tracksInfo: AlbumTracksInfo = {
	tracks: [],
	total_tracks: 20,
	selected_release_mbid: 'release-20'
};

function renderHeader({
	onrefresh = vi.fn(),
	libraryTrackCount = 20,
	libraryBelowCutoff = false
}: {
	onrefresh?: () => void;
	libraryTrackCount?: number;
	libraryBelowCutoff?: boolean;
} = {}) {
	render(AlbumHeader, {
		album,
		tracksInfo,
		loadingTracks: false,
		inLibrary: true,
		isRequested: false,
		requesting: false,
		refreshing: false,
		headerDownloadTask: null,
		downloadClientConfigured: true,
		libraryInLibrary: true,
		libraryTrackCount,
		libraryBelowCutoff,
		mbTrackCount: 20,
		releaseGroupMbid: album.musicbrainz_id,
		onrequest: vi.fn(),
		ondelete: vi.fn(),
		onrefresh,
		onartistclick: vi.fn()
	});
	return onrefresh;
}

describe('AlbumHeader automatic edition selection', () => {
	beforeEach(() => {
		h.setPin.mockReset().mockResolvedValue(undefined);
		h.clearPin.mockReset().mockResolvedValue(undefined);
		h.acquire.mockReset().mockResolvedValue({
			release_mbid: 'release-20',
			total_tracks: 20,
			requested: 0,
			upgrades: 0,
			skipped: 20
		});
		h.editions = {
			items: [
				{
					release_mbid: 'release-11',
					track_count: 11,
					title: 'Avalon',
					disambiguation: null,
					date: '2008-08-04',
					country: 'XW',
					packaging: null,
					status: 'Official',
					is_owned: false,
					is_pinned: false
				},
				{
					release_mbid: 'release-20',
					track_count: 20,
					title: 'Avalon',
					disambiguation: null,
					date: '2008-08-05',
					country: 'US',
					packaging: null,
					status: 'Official',
					is_owned: false,
					is_pinned: false
				}
			],
			pinned_release_mbid: null,
			owned_release_mbid: null,
			selected_release_mbid: 'release-11'
		};
	});

	it('shows the refreshed automatic match and refreshes after a manual pin', async () => {
		const onrefresh = renderHeader();
		const trigger = page.getByRole('button', {
			name: 'Edition: Automatic · 2008 · US · 20 tracks'
		});

		await expect.element(trigger).toBeVisible();
		await expect.element(page.getByText('Edition complete', { exact: true })).toBeVisible();
		await expect
			.element(page.getByRole('button', { name: 'Acquire this edition' }))
			.not.toBeInTheDocument();
		await trigger.click();
		await expect.element(page.getByText('automatic', { exact: true })).toBeVisible();

		await page.getByRole('button', { name: '2008 · XW · 11 tracks' }).click();
		await vi.waitFor(() => {
			expect(h.setPin).toHaveBeenCalledWith({
				mbid: album.musicbrainz_id,
				releaseMbid: 'release-11'
			});
			expect(onrefresh).toHaveBeenCalledOnce();
		});
	});

	it('offers to complete a partial edition', async () => {
		renderHeader({ libraryTrackCount: 11 });

		await expect.element(page.getByRole('button', { name: 'Complete this edition' })).toBeVisible();
		await expect
			.element(page.getByText('Edition complete', { exact: true }))
			.not.toBeInTheDocument();
	});

	it('offers to upgrade a complete edition below the cutoff', async () => {
		renderHeader({ libraryBelowCutoff: true });

		await expect.element(page.getByRole('button', { name: 'Upgrade this edition' })).toBeVisible();
	});
});
