import { beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({
	goto: vi.fn(),
	cache: vi.fn().mockResolvedValue(undefined),
	localView: vi.fn(),
	providerView: vi.fn(),
	album: {
		id: 'local-album-id',
		musicbrainz_release_group_id: 'provider-album-id' as string | null
	}
}));

vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => h.goto(...args)
}));

vi.mock('./LocalAlbumPage.svelte', () => {
	const Component = function () {
		h.localView();
	};
	Component.prototype = {};
	return { default: Component };
});

vi.mock('./ProviderAlbumPage.svelte', () => {
	const Component = function () {
		h.providerView();
	};
	Component.prototype = {};
	return { default: Component };
});

vi.mock('$lib/queries/library/LibraryQueries.svelte', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/queries/library/LibraryQueries.svelte')>()),
	getLibraryAlbumDetailQuery: () => ({
		data: h.album,
		isLoading: false
	}),
	cacheCanonicalLibraryAlbumDetail: (...args: unknown[]) => h.cache(...args)
}));

import AlbumPage from './+page.svelte';

beforeEach(() => {
	vi.clearAllMocks();
	h.album.musicbrainz_release_group_id = 'provider-album-id';
});

it('keeps a linked album on its MusicBrainz release-group route', async () => {
	render(AlbumPage, {
		props: { data: { albumId: 'provider-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => expect(h.goto).not.toHaveBeenCalled());
	expect(h.cache).not.toHaveBeenCalled();
	expect(h.providerView).toHaveBeenCalled();
	expect(h.localView).not.toHaveBeenCalled();
});

it('replaces a linked local route with its MusicBrainz release-group route', async () => {
	render(AlbumPage, {
		props: { data: { albumId: 'local-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => {
		expect(h.goto).toHaveBeenCalledWith('/album/provider-album-id', {
			replaceState: true
		});
	});
	expect(h.cache).toHaveBeenCalledWith(expect.objectContaining({ id: 'local-album-id' }));
	expect(h.providerView).not.toHaveBeenCalled();
	expect(h.localView).not.toHaveBeenCalled();
});

it('keeps a local-only album on its local route', async () => {
	h.album.musicbrainz_release_group_id = null;
	render(AlbumPage, {
		props: { data: { albumId: 'local-album-id' } }
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => expect(h.goto).not.toHaveBeenCalled());
	expect(h.localView).toHaveBeenCalled();
	expect(h.providerView).not.toHaveBeenCalled();
});
