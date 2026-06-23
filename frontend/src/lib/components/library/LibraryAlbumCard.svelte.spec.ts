import { page } from '@vitest/browser/context';
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import LibraryAlbumCard from './LibraryAlbumCard.svelte';
import type { LibraryAlbumSummary } from '$lib/types';

const baseAlbum: LibraryAlbumSummary = {
	release_group_mbid: 'b1392450-e666-3926-a536-22c65f834433',
	album_title: 'OK Computer',
	album_artist_name: 'Radiohead',
	track_count: 12,
	total_size_bytes: 123456,
	quality_format: 'flac',
	year: 1997,
	is_compilation: false,
	cover_url: null,
	last_imported_at: null
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
		renderComponent({ quality_format: 'mp3' });
		await expect.element(page.getByText('MP3')).toBeInTheDocument();
	});

	it('shows the track count', async () => {
		renderComponent();
		await expect.element(page.getByText('12 tracks')).toBeInTheDocument();
	});
});
