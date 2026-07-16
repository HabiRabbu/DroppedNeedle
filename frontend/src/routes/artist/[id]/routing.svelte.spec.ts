import { beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({ goto: vi.fn() }));

vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => h.goto(...args)
}));

vi.mock('$lib/queries/library/LibraryQueries.svelte', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/queries/library/LibraryQueries.svelte')>()),
	getLibraryArtistDetailQuery: () => ({
		data: {
			id: 'local-artist-id',
			musicbrainz_artist_id: 'provider-artist-id'
		},
		isLoading: false
	})
}));

import type { MusicSource } from '$lib/stores/musicSource';
import ArtistPage from './+page.svelte';

beforeEach(() => vi.clearAllMocks());

it('forwards an old local artist link to the familiar provider page', async () => {
	render(ArtistPage, {
		props: {
			data: {
				artistId: 'local-artist-id',
				primarySource: 'listenbrainz' as MusicSource
			}
		}
	} as unknown as Parameters<typeof render>[1]);

	await vi.waitFor(() => {
		expect(h.goto).toHaveBeenCalledWith('/artist/provider-artist-id', {
			replaceState: true
		});
	});
});
