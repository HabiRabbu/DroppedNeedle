import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { ManualReviewEntry } from '$lib/types';

const h = vi.hoisted(() => ({
	query: { isLoading: false, isError: false, error: null, data: { items: [], total: 0 } } as {
		isLoading: boolean;
		isError: boolean;
		error: { message: string } | null;
		data: { items: ManualReviewEntry[]; total: number } | undefined;
	}
}));

vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryUnmatchedQuery: () => h.query,
	getAlbumSearchQuery: () => ({ data: [], isFetching: false }),
	getAlbumTracksQuery: () => ({ data: { tracks: [] }, isLoading: false })
}));

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	resolveUnmatchedBatch: () => ({ mutateAsync: vi.fn(), isPending: false }),
	resolveUnmatchedFile: () => ({ mutateAsync: vi.fn(), isPending: false })
}));
vi.mock('$lib/utils/errorHandling', () => ({ getCoverUrl: () => '/cover.png' }));

function mk(
	partial: Partial<ManualReviewEntry> & { id: number; file_path: string }
): ManualReviewEntry {
	return {
		extracted_title: null,
		extracted_artist: null,
		extracted_album: null,
		extracted_year: null,
		track_number: null,
		disc_number: null,
		file_format: 'flac',
		duration: null,
		file_size: null,
		fingerprint: null,
		fingerprint_score: null,
		candidate_mbids: [],
		source: 'text_match',
		created_at: null,
		...partial
	};
}

import LibraryUnmatched from './LibraryUnmatched.svelte';

describe('LibraryUnmatched.svelte', () => {
	beforeEach(() => {
		h.query = { isLoading: false, isError: false, error: null, data: { items: [], total: 0 } };
	});

	it('shows the clean empty state when nothing needs review', async () => {
		render(LibraryUnmatched);
		await expect.element(page.getByText('No files need review')).toBeVisible();
	});

	it('renders one card per folder with the guessed album + artist', async () => {
		h.query = {
			isLoading: false,
			isError: false,
			error: null,
			data: {
				total: 3,
				items: [
					mk({
						id: 1,
						file_path: '/m/OK Computer/01.flac',
						extracted_album: 'OK Computer',
						extracted_artist: 'Radiohead'
					}),
					mk({
						id: 2,
						file_path: '/m/OK Computer/02.flac',
						extracted_album: 'OK Computer',
						extracted_artist: 'Radiohead'
					}),
					mk({
						id: 3,
						file_path: '/m/Kid A/01.flac',
						extracted_album: 'Kid A',
						extracted_artist: 'Radiohead'
					})
				]
			}
		};
		render(LibraryUnmatched);
		await expect.element(page.getByRole('heading', { name: 'OK Computer' })).toBeVisible();
		await expect.element(page.getByRole('heading', { name: 'Kid A' })).toBeVisible();
		await expect
			.element(page.getByText('3 files across 2 folders need attributing.'))
			.toBeVisible();
	});
});
