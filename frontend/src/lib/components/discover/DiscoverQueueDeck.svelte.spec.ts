import { page } from '@vitest/browser/context';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-svelte';

vi.mock('$env/dynamic/public', () => ({
	env: { PUBLIC_API_URL: '' }
}));

const { deckMock, samplerStart, requestAlbum } = vi.hoisted(() => {
	const items = [
		{
			release_group_mbid: 'rg-1',
			album_name: 'The Bends',
			artist_name: 'The Verve',
			artist_mbid: 'artist-1',
			cover_url: null,
			recommendation_reason: 'Similar to Radiohead',
			is_wildcard: false,
			in_library: false,
			enrichment: {
				artist_mbid: 'artist-1',
				release_date: '1995-03-13',
				country: 'GB',
				tags: ['alt-rock', 'britpop'],
				youtube_url: null,
				youtube_search_url: 'https://youtube.example/search',
				youtube_search_available: true,
				artist_description: 'Formed in Wigan in 1989, the band went on to…',
				listen_count: 2100000
			}
		},
		{
			release_group_mbid: 'rg-2',
			album_name: 'Urban Hymns',
			artist_name: 'The Verve',
			artist_mbid: 'artist-1',
			cover_url: null,
			recommendation_reason: 'Similar to Radiohead',
			is_wildcard: false,
			in_library: false,
			enrichment: null
		}
	];
	return {
		deckMock: {
			phase: 'ready' as string,
			queue: items,
			currentIndex: 0,
			get current() {
				return this.queue[this.currentIndex];
			},
			get isLast() {
				return this.currentIndex >= this.queue.length - 1;
			},
			errorMessage: '',
			init: vi.fn().mockResolvedValue(undefined),
			next: vi.fn(),
			previous: vi.fn(),
			jumpTo: vi.fn(),
			ignoreCurrent: vi.fn().mockResolvedValue(undefined),
			markCurrentRequested: vi.fn(),
			finish: vi.fn(),
			retryBuild: vi.fn(),
			buildNow: vi.fn(),
			destroy: vi.fn()
		},
		samplerStart: vi.fn().mockResolvedValue(undefined),
		requestAlbum: vi.fn().mockResolvedValue({ success: true })
	};
});

vi.mock('$lib/stores/discoverQueueDeck.svelte', () => ({
	discoverQueueDeck: deckMock
}));

vi.mock('$lib/stores/deckSampler.svelte', () => ({
	deckSampler: {
		status: 'idle',
		tracks: [],
		trackIndex: 0,
		currentTrack: null,
		provider: null,
		progress: 0,
		activeKey: '',
		start: (...args: unknown[]) => samplerStart(...args),
		stop: vi.fn()
	}
}));

vi.mock('$lib/stores/audioFocus.svelte', () => ({
	audioFocus: { claim: vi.fn(), release: vi.fn(), interrupt: vi.fn(), holder: null }
}));

vi.mock('$lib/stores/player.svelte', () => ({
	playerStore: { isPlaying: false, pause: vi.fn() }
}));

vi.mock('$lib/utils/albumRequest', () => ({
	requestAlbum: (...args: unknown[]) => requestAlbum(...args)
}));

vi.mock('$lib/stores/integration', async () => {
	const { readable } = await import('svelte/store');
	return {
		integrationStore: readable({ download_client: true, youtube: true, youtube_api: true })
	};
});

vi.mock('$lib/api/client', () => ({
	api: {
		global: {
			get: vi.fn().mockResolvedValue({ used: 0, limit: 100, remaining: 100 }),
			post: vi.fn().mockResolvedValue({})
		}
	}
}));

import DiscoverQueueDeck from './DiscoverQueueDeck.svelte';

describe('DiscoverQueueDeck', () => {
	beforeEach(() => {
		deckMock.phase = 'ready';
		deckMock.currentIndex = 0;
		vi.clearAllMocks();
	});

	it('renders the current item with reason, links, meta and tags', async () => {
		render(DiscoverQueueDeck);

		await expect.element(page.getByText('Similar to Radiohead')).toBeVisible();
		const albumLink = page.getByRole('link', { name: 'The Bends', exact: true });
		await expect.element(albumLink).toHaveAttribute('href', '/album/rg-1');
		const artistLink = page.getByRole('link', { name: 'The Verve', exact: true });
		await expect.element(artistLink).toHaveAttribute('href', '/artist/artist-1');
		await expect.element(page.getByText('1995')).toBeVisible();
		await expect.element(page.getByRole('link', { name: 'alt-rock' })).toBeVisible();
		await expect.element(page.getByText('1 / 2')).toBeVisible();
	});

	it('Next advances the deck', async () => {
		render(DiscoverQueueDeck);

		await page.getByRole('button', { name: /^Next$/ }).click();
		expect(deckMock.next).toHaveBeenCalledTimes(1);
	});

	it('Not for me ignores the current item', async () => {
		render(DiscoverQueueDeck);

		await page.getByRole('button', { name: /Not for me/ }).click();
		expect(deckMock.ignoreCurrent).toHaveBeenCalledTimes(1);
	});

	it('Request files an album request and marks it', async () => {
		render(DiscoverQueueDeck);

		await page.getByRole('button', { name: /^Request$/ }).click();
		await vi.waitFor(() => {
			expect(requestAlbum).toHaveBeenCalledWith('rg-1', {
				artist: 'The Verve',
				album: 'The Bends',
				artistMbid: 'artist-1'
			});
		});
		expect(deckMock.markCurrentRequested).toHaveBeenCalled();
	});

	it('Sample album starts the sampler for the current item', async () => {
		render(DiscoverQueueDeck);

		await page.getByRole('button', { name: /Sample album/ }).click();
		expect(samplerStart).toHaveBeenCalledWith('rg-1', 'The Verve', 'The Bends');
	});

	it('filmstrip jump navigates to the clicked item', async () => {
		render(DiscoverQueueDeck);

		await page.getByRole('tab', { name: /Urban Hymns/ }).click();
		expect(deckMock.jumpTo).toHaveBeenCalledWith(1);
	});

	it('building phase shows the equalizer state', async () => {
		deckMock.phase = 'building';
		render(DiscoverQueueDeck);

		await expect.element(page.getByText('Building your personalised queue…')).toBeVisible();
		await expect.element(page.getByRole('button', { name: /Build now instead/ })).toBeVisible();
	});

	it('error phase offers retry', async () => {
		deckMock.phase = 'error';
		render(DiscoverQueueDeck);

		await page.getByRole('button', { name: /Retry/ }).click();
		expect(deckMock.retryBuild).toHaveBeenCalled();
	});
});
