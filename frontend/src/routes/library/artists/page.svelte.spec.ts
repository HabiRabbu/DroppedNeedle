import { page } from '@vitest/browser/context';
import { expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

vi.mock('$lib/components/ArtistImage.svelte', () => {
	const Component = function () {};
	Component.prototype = {};
	return { default: Component };
});

vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryArtistsInfiniteQuery: () => ({
		data: {
			pages: [
				{
					total: 2,
					items: [
						{
							id: 'local-linked-artist',
							name: 'Linked Artist',
							musicbrainz_artist_id: 'provider-artist-id',
							artist_identity_state: 'musicbrainz_linked',
							album_count: 2,
							track_count: 20,
							date_added: 1,
							row_revision: 1
						},
						{
							id: 'local-only-artist',
							name: 'Local Artist',
							musicbrainz_artist_id: null,
							artist_identity_state: 'local_only',
							album_count: 1,
							track_count: 8,
							date_added: 2,
							row_revision: 1
						}
					]
				}
			]
		},
		isError: false,
		isLoading: false,
		hasNextPage: false,
		isFetchingNextPage: false,
		refetch: vi.fn(),
		fetchNextPage: vi.fn()
	})
}));

import ArtistsPage from './+page.svelte';

it('uses local artist routes and marks only local-only cards', async () => {
	render(ArtistsPage);

	await expect
		.element(page.getByRole('link', { name: 'Open Linked Artist' }))
		.toHaveAttribute('href', '/artist/local-linked-artist');
	await expect
		.element(page.getByRole('link', { name: 'Open Local Artist' }))
		.toHaveAttribute('href', '/artist/local-only-artist');
	await expect.element(page.getByText('Local-only', { exact: true })).toBeVisible();
	await expect
		.element(page.getByText('MusicBrainz linked', { exact: true }))
		.not.toBeInTheDocument();
});
