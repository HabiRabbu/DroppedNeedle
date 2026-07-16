import { beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({ goto: vi.fn() }));

vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => h.goto(...args)
}));

vi.mock('$lib/queries/library/LibraryQueries.svelte', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/queries/library/LibraryQueries.svelte')>()),
	getLibraryAlbumDetailQuery: () => ({
		data: {
			id: 'local-album-id',
			musicbrainz_release_group_id: 'provider-album-id'
		},
		isLoading: false
	})
}));

import AlbumPage from './+page.svelte';

beforeEach(() => vi.clearAllMocks());

it('forwards an old local album link to the familiar provider page', async () => {
	render(AlbumPage, {
		props: { data: { albumId: 'local-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => {
		expect(h.goto).toHaveBeenCalledWith('/album/provider-album-id', {
			replaceState: true
		});
	});
});
