import { page } from '@vitest/browser/context';
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import LibraryAlbumCard from './LibraryAlbumCard.svelte';
import type { LibraryAlbumSummary } from '$lib/types';

const baseAlbum: LibraryAlbumSummary = {
	id: 'local-album-1',
	title: 'OK Computer',
	artist_name: 'Radiohead',
	artist_id: 'local-artist-1',
	musicbrainz_release_group_id: 'b1392450-e666-3926-a536-22c65f834433',
	musicbrainz_artist_id: null,
	track_count: 12,
	total_duration_seconds: 3200,
	total_size_bytes: 123456,
	format: 'flac',
	year: 1997,
	is_compilation: false,
	cover_available: false,
	date_added: null,
	sort_name: null,
	original_release_date: null
};

function renderComponent(overrides: Partial<LibraryAlbumSummary> = {}) {
	return render(LibraryAlbumCard, {
		props: { album: { ...baseAlbum, ...overrides } }
	} as Parameters<typeof render<typeof LibraryAlbumCard>>[1]);
}

describe('LibraryAlbumCard.svelte', () => {
	it('shows the album title', async () => {
		renderComponent();
		await expect.element(page.getByText('OK Computer')).toBeInTheDocument();
	});

	it('shows the album artist', async () => {
		renderComponent();
		await expect.element(page.getByText(/Radiohead/)).toBeInTheDocument();
	});

	it('shows a FLAC format badge for flac albums', async () => {
		renderComponent();
		await expect.element(page.getByText('FLAC')).toBeInTheDocument();
	});

	it('shows an MP3 format badge for mp3 albums', async () => {
		renderComponent({ format: 'mp3' });
		await expect.element(page.getByText('MP3')).toBeInTheDocument();
	});

	it('shows the track count', async () => {
		renderComponent();
		await expect.element(page.getByText('12 tracks')).toBeInTheDocument();
	});

	it('opens identified albums on the familiar provider route', async () => {
		renderComponent();
		await expect
			.element(page.getByRole('link', { name: 'Open OK Computer' }))
			.toHaveAttribute('href', '/album/b1392450-e666-3926-a536-22c65f834433');
	});

	it('uses the unified album route for local-only albums', async () => {
		renderComponent({ musicbrainz_release_group_id: null });
		await expect
			.element(page.getByRole('link', { name: 'Open OK Computer' }))
			.toHaveAttribute('href', '/album/local-album-1');
	});
});
