import { beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({ goto: vi.fn(), cache: vi.fn().mockResolvedValue(undefined) }));

vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => h.goto(...args)
}));

vi.mock('./LocalAlbumPage.svelte', () => {
	const Component = function () {};
	Component.prototype = {};
	return { default: Component };
});

vi.mock('./ProviderAlbumPage.svelte', () => {
	const Component = function () {};
	Component.prototype = {};
	return { default: Component };
});

vi.mock('$lib/queries/library/LibraryQueries.svelte', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/queries/library/LibraryQueries.svelte')>()),
	getLibraryAlbumDetailQuery: () => ({
		data: {
			id: 'local-album-id',
			musicbrainz_release_group_id: 'provider-album-id'
		},
		isLoading: false
	}),
	cacheCanonicalLibraryAlbumDetail: (...args: unknown[]) => h.cache(...args)
}));

import AlbumPage from './+page.svelte';

beforeEach(() => vi.clearAllMocks());

it('replaces a uniquely owned provider route with the canonical local route', async () => {
	render(AlbumPage, {
		props: { data: { albumId: 'provider-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => {
		expect(h.goto).toHaveBeenCalledWith('/album/local-album-id', {
			replaceState: true
		});
	});
	expect(h.cache).toHaveBeenCalledWith(expect.objectContaining({ id: 'local-album-id' }));
});

it('does not redirect an owned album already using its local route', async () => {
	render(AlbumPage, {
		props: { data: { albumId: 'local-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => expect(h.goto).not.toHaveBeenCalled());
});
