import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { LibraryFileMeta, TrackTagUpdate } from '$lib/types';

const { mockGet, mockSave } = vi.hoisted(() => ({ mockGet: vi.fn(), mockSave: vi.fn() }));

vi.mock('$lib/api/client', () => ({
	api: { global: { get: (...args: unknown[]) => mockGet(...args) } }
}));

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	updateTrackTags: () => ({ mutateAsync: mockSave, isPending: false })
}));

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

import TagEditor from './TagEditor.svelte';

const track: LibraryFileMeta = {
	id: 'file-1',
	title: 'Airbag',
	album_id: 'album-1',
	album_title: 'OK Computer',
	artist_id: 'artist-1',
	artist_name: 'Radiohead',
	album_artist_id: 'artist-1',
	album_artist_name: 'Radiohead',
	musicbrainz_recording_id: 'rec-1',
	musicbrainz_release_group_id: null,
	musicbrainz_artist_id: null,
	musicbrainz_album_artist_id: null,
	disc_number: 1,
	track_number: 1,
	year: 1997,
	genre: 'Rock',
	duration_seconds: 260,
	format: 'flac',
	bit_rate: 900,
	sample_rate: 44100,
	bit_depth: 16,
	channels: 2,
	file_size_bytes: 1048576,
	date_added: 1,
	cover_available: false,
	current_tier: 'lossless',
	below_cutoff: false
};

const loadedTags: TrackTagUpdate = {
	title: 'Airbag',
	artist: 'Radiohead',
	album: 'OK Computer',
	track_number: 1,
	album_artist: 'Radiohead',
	disc_number: 1,
	year: 1997,
	genre: 'Rock',
	musicbrainz_release_group_id: 'rg-ok',
	musicbrainz_release_id: null,
	musicbrainz_recording_id: null,
	musicbrainz_artist_id: null,
	musicbrainz_album_artist_id: null
};

function renderEditor() {
	return render(TagEditor, {
		props: { track, releaseGroupMbid: 'rg-ok', open: true }
	} as Parameters<typeof render<typeof TagEditor>>[1]);
}

describe('TagEditor.svelte', () => {
	beforeEach(() => {
		mockGet.mockReset();
		mockGet.mockResolvedValue({ ...loadedTags });
		mockSave.mockReset();
		mockSave.mockResolvedValue({});
	});

	it('fetches the track tags from disk when opened', async () => {
		renderEditor();
		await expect.element(page.getByText('Edit tags')).toBeVisible();
		// Save is disabled until the prefill load resolves; waiting for it to enable
		// guarantees the GET has run.
		await expect.element(page.getByRole('button', { name: 'Save' })).toBeEnabled();
		expect(mockGet).toHaveBeenCalledWith('/api/v1/library/tracks/file-1/tags');
	});

	it('saves the prefilled tags immediately when no MBID changed', async () => {
		renderEditor();
		// click() auto-waits for the button to become enabled (i.e. load finished).
		await page.getByRole('button', { name: 'Save' }).click();
		expect(mockSave).toHaveBeenCalledWith(
			expect.objectContaining({
				fileId: 'file-1',
				releaseGroupMbid: 'rg-ok',
				tags: expect.objectContaining({ title: 'Airbag', album: 'OK Computer' })
			})
		);
	});
});
