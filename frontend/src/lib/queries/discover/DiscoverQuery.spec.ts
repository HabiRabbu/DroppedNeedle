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

describe('getPlaylistSuggestionsQuery source propagation', () => {
	it('passes listenbrainz source in request body', async () => {
		mockPost.mockResolvedValue({ playlist_id: 'pl-1', suggestions: { items: [] } });

		const { getPlaylistSuggestionsQuery } = await import('./DiscoverQuery.svelte');

		const getter = () => ({
			playlistId: 'pl-1',
			count: 10,
			source: 'listenbrainz' as const,
			enabled: true
		});

		getPlaylistSuggestionsQuery(getter);

		expect(mockCreateQuery).toHaveBeenCalled();
		const factory = mockCreateQuery.mock.calls[
			mockCreateQuery.mock.calls.length - 1
		][0] as unknown as () => Record<string, unknown>;
		const opts = factory();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect((body as Record<string, unknown>).source).toBe('listenbrainz');
	});

	it('passes lastfm source in request body', async () => {
		mockPost.mockResolvedValue({ playlist_id: 'pl-1', suggestions: { items: [] } });

		const { getPlaylistSuggestionsQuery } = await import('./DiscoverQuery.svelte');

		const getter = () => ({
			playlistId: 'pl-1',
			count: 10,
			source: 'lastfm' as const,
			enabled: true
		});

		getPlaylistSuggestionsQuery(getter);

		const factory = mockCreateQuery.mock.calls[
			mockCreateQuery.mock.calls.length - 1
		][0] as unknown as () => Record<string, unknown>;
		const opts = factory();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect((body as Record<string, unknown>).source).toBe('lastfm');
	});
});

describe('getRadioQuery source propagation', () => {
	it('passes source in request body', async () => {
		mockPost.mockResolvedValue({ items: [] });

		const { getRadioQuery } = await import('./DiscoverQuery.svelte');

		const getter = () => ({
			seedType: 'artist',
			seedId: 'mbid-123',
			source: 'listenbrainz' as const
		});

		getRadioQuery(getter);

		const factory = mockCreateQuery.mock.calls[
			mockCreateQuery.mock.calls.length - 1
		][0] as unknown as () => Record<string, unknown>;
		const opts = factory();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect((body as Record<string, unknown>).source).toBe('listenbrainz');
	});

	it('passes lastfm source in request body', async () => {
		mockPost.mockResolvedValue({ items: [] });

		const { getRadioQuery } = await import('./DiscoverQuery.svelte');

		const getter = () => ({
			seedType: 'artist',
			seedId: 'mbid-456',
			source: 'lastfm' as const
		});

		getRadioQuery(getter);

		const factory = mockCreateQuery.mock.calls[
			mockCreateQuery.mock.calls.length - 1
		][0] as unknown as () => Record<string, unknown>;
		const opts = factory();
		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });

		expect(mockPost).toHaveBeenCalledTimes(1);
		const [, body] = mockPost.mock.calls[0];
		expect((body as Record<string, unknown>).source).toBe('lastfm');
	});
});
