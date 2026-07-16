import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { LibraryAlbumDetail, NativeTrackListItem } from '$lib/types';

const h = vi.hoisted(() => ({
	playQueue: vi.fn(),
	goto: vi.fn()
}));

vi.mock('$app/state', () => ({ page: { params: { id: 'local-album-1' } } }));
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => h.goto(...args) }));
vi.mock('$lib/stores/authStore.svelte', () => ({ authStore: { isAdmin: false } }));
vi.mock('$lib/stores/player.svelte', () => ({
	playerStore: { playQueue: (...args: unknown[]) => h.playQueue(...args) }
}));

const album: LibraryAlbumDetail = {
	id: 'local-album-1',
	title: 'Local Only Album',
	artist_name: 'Local Artist',
	artist_id: 'local-artist-1',
	musicbrainz_release_group_id: null,
	musicbrainz_artist_id: null,
	track_count: 1,
	total_duration_seconds: 181,
	total_size_bytes: 1024,
	format: 'flac',
	year: 2026,
	is_compilation: false,
	cover_available: false,
	date_added: 1,
	sort_name: null,
	original_release_date: null,
	row_revision: 2,
	input_revision: 'input-2',
	identification_status: 'local_metadata',
	review_id: null,
	review_revision: null
};

const track: NativeTrackListItem = {
	id: 'local-track-1',
	title: 'Unmatched Song',
	album_id: album.id,
	album_title: album.title,
	artist_id: album.artist_id,
	artist_name: album.artist_name,
	album_artist_id: album.artist_id,
	album_artist_name: album.artist_name,
	musicbrainz_recording_id: null,
	musicbrainz_release_group_id: null,
	musicbrainz_artist_id: null,
	musicbrainz_album_artist_id: null,
	disc_number: 1,
	track_number: 1,
	year: 2026,
	genre: 'Electronic',
	duration_seconds: 181,
	format: 'flac',
	bit_rate: 900000,
	sample_rate: 48000,
	bit_depth: 24,
	channels: 2,
	file_size_bytes: 1024,
	date_added: 1,
	cover_available: false,
	current_tier: null,
	below_cutoff: false
};

vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryAlbumsQuery: () => ({ data: { items: [] } }),
	getLibraryAlbumDetailQuery: () => ({
		data: album,
		isLoading: false,
		isError: false,
		refetch: vi.fn()
	}),
	getLibraryAlbumTracksQuery: () => ({
		data: { items: [track], total: 1, offset: 0, limit: 100 },
		isLoading: false,
		isError: false
	})
}));

import LocalAlbumPage from './LocalAlbumPage.svelte';

beforeEach(() => {
	vi.clearAllMocks();
});

describe('local-only album page', () => {
	it('plays stable local tracks and explains why alternate editions are unavailable', async () => {
		render(LocalAlbumPage, {
			props: { albumId: album.id }
		} as unknown as Parameters<typeof render>[1]);

		await expect.element(page.getByRole('heading', { name: 'Local Only Album' })).toBeVisible();
		await expect.element(page.getByText('Local metadata', { exact: true })).toBeVisible();
		const alternateEditions = page.getByRole('button', { name: 'Browse alternate editions' });
		await expect.element(alternateEditions).toBeDisabled();
		await expect
			.element(page.getByText('Identify this album before searching for alternate editions.'))
			.toBeVisible();

		await page.getByRole('button', { name: 'Play', exact: true }).click();
		expect(h.playQueue).toHaveBeenCalledWith(
			[
				expect.objectContaining({
					trackSourceId: 'local-track-1',
					sourceType: 'local',
					albumId: 'local-album-1',
					streamUrl: expect.stringContaining('local-track-1')
				})
			],
			0,
			false
		);
	});
});
