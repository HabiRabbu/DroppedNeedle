import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((factory: () => Record<string, unknown>) => {
		const opts = factory();
		return opts;
	}),
	queryOptions: vi.fn((opts: Record<string, unknown>) => opts)
}));

vi.mock('$lib/api/client', async () => {
	class ApiErrorMock extends Error {
		readonly status: number;
		readonly code: string;
		readonly details: unknown;
		constructor(status: number, message: string, code = '', details: unknown = null) {
			super(message);
			this.name = 'ApiError';
			this.status = status;
			this.code = code;
			this.details = details;
		}
	}
	return {
		ApiError: ApiErrorMock,
		api: {
			global: {
				get: vi.fn(),
				post: vi.fn()
			}
		}
	};
});

import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';

const mockPost = vi.mocked(api.global.post);
const mockCreateQuery = vi.mocked(createQuery);

beforeEach(() => {
	vi.clearAllMocks();
});

function lastQueryOpts(): Record<string, unknown> {
	const factory = mockCreateQuery.mock.calls[
		mockCreateQuery.mock.calls.length - 1
	][0] as unknown as () => Record<string, unknown>;
	return factory();
}

describe('getPlaylistSuggestionsQuery', () => {
	it('posts the playlist id and count (no source: backend resolves the primary)', async () => {
		mockPost.mockResolvedValue({ playlist_id: 'pl-1', suggestions: { items: [] } });

		const { getPlaylistSuggestionsQuery } = await import('./DiscoverQuery.svelte');

		getPlaylistSuggestionsQuery(() => ({
			playlistId: 'pl-1',
			count: 10,
			enabled: true
		}));

		const opts = lastQueryOpts();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect(body).toEqual({ playlist_id: 'pl-1', count: 10 });
	});

	it('is disabled without a playlist id', async () => {
		const { getPlaylistSuggestionsQuery } = await import('./DiscoverQuery.svelte');

		getPlaylistSuggestionsQuery(() => ({ playlistId: '', enabled: true }));

		const opts = lastQueryOpts();
		expect(opts.enabled).toBe(false);
	});
});

describe('getRadioQuery', () => {
	it('posts the seed (no source: backend resolves the primary)', async () => {
		mockPost.mockResolvedValue({ items: [] });

		const { getRadioQuery } = await import('./DiscoverQuery.svelte');

		getRadioQuery(() => ({
			seedType: 'artist',
			seedId: 'mbid-123'
		}));

		const opts = lastQueryOpts();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect(body).toEqual({ seed_type: 'artist', seed_id: 'mbid-123' });
	});

	it('carries the seed in the query key', async () => {
		mockPost.mockResolvedValue({ items: [] });

		const { getRadioQuery } = await import('./DiscoverQuery.svelte');

		getRadioQuery(() => ({ seedType: 'genre', seedId: 'shoegaze' }));

		const opts = lastQueryOpts();
		expect(opts.queryKey).toContain('radio');
		expect(opts.queryKey).toContain('genre');
		expect(opts.queryKey).toContain('shoegaze');
	});

	it('can defer the individual station request until its card is expanded', async () => {
		const { getRadioQuery } = await import('./DiscoverQuery.svelte');

		getRadioQuery(() => ({ seedType: 'artist', seedId: 'mbid-123', enabled: false }));

		const opts = lastQueryOpts();
		expect(opts.enabled).toBe(false);
	});
});
