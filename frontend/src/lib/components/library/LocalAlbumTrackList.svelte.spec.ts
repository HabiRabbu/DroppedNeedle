import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { NativeTrackListItem } from '$lib/types';

vi.mock('$lib/stores/player.svelte', () => ({
	playerStore: { playQueue: vi.fn() }
}));

import LocalAlbumTrackList from './LocalAlbumTrackList.svelte';

function track(
	id: string,
	title: string,
	artistId: string,
	artistName: string
): NativeTrackListItem {
	return {
		id,
		title,
		album_id: 'compilation-1',
		album_title: 'Night Signals',
		artist_id: artistId,
		artist_name: artistName,
		album_artist_id: 'various-artists',
		album_artist_name: 'Various Artists',
		musicbrainz_recording_id: null,
		musicbrainz_release_group_id: null,
		musicbrainz_artist_id: null,
		musicbrainz_album_artist_id: null,
		disc_number: 1,
		track_number: id === 'track-1' ? 1 : 2,
		year: 2026,
		genre: 'Electronic',
		duration_seconds: 180,
		format: 'flac',
		bit_rate: null,
		sample_rate: 44100,
		bit_depth: 16,
		channels: 2,
		file_size_bytes: 1000,
		date_added: 1,
		cover_available: false,
		current_tier: 'lossless',
		below_cutoff: false
	};
}

describe('LocalAlbumTrackList', () => {
	it('keeps compilation track credits linked to their stable local artists', async () => {
		render(LocalAlbumTrackList, {
			props: {
				tracks: [
					track('track-1', 'Northbound', 'artist-north', 'North Signal'),
					track('track-2', 'Southbound', 'artist-south', 'South Signal')
				]
			}
		} as unknown as Parameters<typeof render>[1]);

		await expect
			.element(page.getByRole('link', { name: 'North Signal' }))
			.toHaveAttribute('href', '/artist/artist-north');
		await expect
			.element(page.getByRole('link', { name: 'South Signal' }))
			.toHaveAttribute('href', '/artist/artist-south');
	});
});
