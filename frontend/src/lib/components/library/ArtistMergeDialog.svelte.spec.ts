import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { LibraryArtistSummary } from '$lib/types';
import type { MembershipPreviewResponse } from '$lib/queries/library/LibraryOperationsTypes';

const artist: LibraryArtistSummary = {
	id: 'artist-1',
	name: 'Primary Artist',
	musicbrainz_artist_id: 'mbid-1',
	artist_identity_state: 'musicbrainz_linked',
	album_count: 3,
	track_count: 20,
	date_added: 1,
	row_revision: 4
};
const duplicate: LibraryArtistSummary = {
	id: 'artist-2',
	name: 'Duplicate Artist',
	musicbrainz_artist_id: 'mbid-2',
	artist_identity_state: 'musicbrainz_linked',
	album_count: 2,
	track_count: 12,
	date_added: 2,
	row_revision: 6
};
const previewResult: MembershipPreviewResponse = {
	preview_token: 'preview-1',
	source_album_ids: [],
	target_album_id: null,
	track_ids: [],
	identity_conflicts: ['mbid-1', 'mbid-2'],
	aliases: ['artist-1'],
	automatic_groups: [],
	reference_counts: { album_credits: 5, track_credits: 18, compatibility_ids: 2 }
};

const h = vi.hoisted(() => ({
	artists: [] as LibraryArtistSummary[],
	duplicate: undefined as LibraryArtistSummary | undefined,
	previewData: undefined as MembershipPreviewResponse | undefined,
	preview: vi.fn(),
	apply: vi.fn(),
	previewReset: vi.fn(),
	goto: vi.fn()
}));

vi.mock('$app/navigation', () => ({ goto: h.goto }));
vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryArtistsInfiniteQuery: () => ({
		get data() {
			return { pages: [{ items: h.artists }] };
		}
	}),
	getLibraryArtistDetailQuery: () => ({
		get data() {
			return h.duplicate;
		}
	})
}));
vi.mock('$lib/queries/library/LibraryCatalogMutations.svelte', () => ({
	previewArtistMerge: () => ({
		mutateAsync: async (input: unknown) => {
			const result = await h.preview(input);
			h.previewData = previewResult;
			return result;
		},
		get data() {
			return h.previewData;
		},
		get isPending() {
			return false;
		},
		reset: () => {
			h.previewData = undefined;
			h.previewReset();
		}
	}),
	applyArtistMerge: () => ({ mutateAsync: h.apply, isPending: false })
}));

import ArtistMergeDialog from './ArtistMergeDialog.svelte';

async function openAndPreview(survivor = 'artist-1'): Promise<void> {
	await page.getByText('Artist organization').click();
	await page.getByRole('button', { name: 'Merge duplicate artist...' }).click();
	await page.getByPlaceholder('Search local artists').fill('Duplicate');
	h.duplicate = duplicate;
	await page.getByRole('radio', { name: /Duplicate Artist/ }).click();
	await expect.element(page.getByText('Choose the surviving local ID')).toBeVisible();
	if (survivor === 'artist-2') {
		await page.getByRole('radio').last().click();
	}
	await page.getByRole('button', { name: 'Preview merge' }).click();
}

beforeEach(() => {
	vi.clearAllMocks();
	h.duplicate = undefined;
	h.artists = [artist, duplicate];
	h.previewData = undefined;
	h.preview.mockResolvedValue(previewResult);
	h.apply.mockResolvedValue({ surviving_artist_id: 'artist-2' });
});

describe('ArtistMergeDialog', () => {
	it('previews the chosen survivor, conflicts, aliases, and compatibility impact', async () => {
		render(ArtistMergeDialog, {
			props: { artist }
		} as unknown as Parameters<typeof render>[1]);
		await openAndPreview('artist-2');
		expect(h.preview).toHaveBeenCalledWith({
			source_artist_ids: ['artist-1', 'artist-2'],
			surviving_artist_id: 'artist-2',
			expected_revisions: { 'artist-1': 4, 'artist-2': 6 }
		});
		await expect.element(page.getByText(/1 previous IDs will remain as aliases/)).toBeVisible();
		await expect
			.element(page.getByText('These artists have conflicting provider identities.'))
			.toBeVisible();
		await expect.element(page.getByText('compatibility ids')).toBeVisible();
		await page.getByRole('radio', { name: /Keep the survivor/ }).click();
		await page.getByRole('checkbox', { name: /preserve the retired IDs/ }).click();
		await page.getByRole('button', { name: 'Merge artists' }).click();
		expect(h.apply).toHaveBeenCalledWith({
			source_artist_ids: ['artist-1', 'artist-2'],
			surviving_artist_id: 'artist-2',
			expected_revisions: { 'artist-1': 4, 'artist-2': 6 },
			preview_token: 'preview-1',
			provider_choice: 'retain_survivor'
		});
		expect(h.goto).toHaveBeenCalledWith('/artist/artist-2');
	});

	it('keeps a stale merge open and requires a fresh preview', async () => {
		h.apply.mockRejectedValue(new Error('stale revision'));
		render(ArtistMergeDialog, {
			props: { artist }
		} as unknown as Parameters<typeof render>[1]);
		await openAndPreview();
		await page.getByRole('checkbox', { name: /preserve the retired IDs/ }).click();
		await page.getByRole('button', { name: 'Merge artists' }).click();
		await expect.element(page.getByText(/artist records changed after this preview/)).toBeVisible();
		await expect.element(page.getByRole('button', { name: 'Preview merge' })).toBeVisible();
		expect(h.goto).not.toHaveBeenCalled();
	});

	it('returns keyboard focus to the menu action that opened the dialog', async () => {
		render(ArtistMergeDialog, {
			props: { artist }
		} as unknown as Parameters<typeof render>[1]);
		await page.getByText('Artist organization').click();
		const opener = page.getByRole('button', { name: 'Merge duplicate artist...' });
		await opener.click();
		await expect
			.element(page.getByRole('heading', { name: 'Merge duplicate artist' }))
			.toHaveFocus();
		await page.getByRole('button', { name: 'Cancel' }).click();
		await expect.element(opener).toHaveFocus();
	});
});
