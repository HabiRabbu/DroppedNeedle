import { describe, expect, it, vi } from 'vitest';

import { DownloadQueryKeyFactory } from './DownloadQueryKeyFactory';

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((factory: () => unknown) => factory()),
	createMutation: vi.fn((factory: () => unknown) => factory()),
	queryOptions: vi.fn((opts: unknown) => opts)
}));

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('$lib/api/client', () => ({
	api: {
		global: {
			get: (...args: unknown[]) => mockGet(...args),
			post: (...args: unknown[]) => mockPost(...args)
		}
	}
}));

const { mockInvalidate } = vi.hoisted(() => ({ mockInvalidate: vi.fn() }));
vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: (...args: unknown[]) => mockInvalidate(...args)
}));

import {
	cancelSearch,
	getSearchJobQueryOptions,
	pickSearchCandidate,
	startAlbumSearch
} from './SearchQueries.svelte';

describe('download search queries', () => {
	it('search-job query hits /downloads/search/{id}', async () => {
		const opts = getSearchJobQueryOptions('job1') as { queryFn: (a: unknown) => unknown };
		await opts.queryFn({ signal: undefined });
		expect(String(mockGet.mock.calls[0][0])).toContain('/downloads/search/job1');
	});

	it('startAlbumSearch posts to /downloads/search/album', async () => {
		const m = startAlbumSearch() as unknown as { mutationFn: (i: unknown) => unknown };
		await m.mutationFn({ artist_name: 'A', album_title: 'B' });
		expect(String(mockPost.mock.calls.at(-1)?.[0])).toContain('/downloads/search/album');
	});

	it('pickSearchCandidate posts to /downloads/search/{id}/pick with the index', async () => {
		const m = pickSearchCandidate() as unknown as {
			mutationFn: (i: { jobId: string; candidate_index: number }) => unknown;
		};
		await m.mutationFn({ jobId: 'job1', candidate_index: 2 });
		const call = mockPost.mock.calls.at(-1);
		expect(String(call?.[0])).toContain('/downloads/search/job1/pick');
		expect(call?.[1]).toEqual({ candidate_index: 2 });
	});

	it('cancelSearch posts to /downloads/search/{id}/cancel', async () => {
		const m = cancelSearch() as unknown as { mutationFn: (i: string) => unknown };
		await m.mutationFn('job1');
		expect(String(mockPost.mock.calls.at(-1)?.[0])).toContain('/downloads/search/job1/cancel');
	});

	it('pickSearchCandidate invalidates the search-job query on success', async () => {
		mockInvalidate.mockClear();
		const m = pickSearchCandidate() as unknown as {
			onSuccess: (d: unknown, i: { jobId: string; candidate_index: number }) => unknown;
		};
		await m.onSuccess({ task_id: 't' }, { jobId: 'job1', candidate_index: 0 });
		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: DownloadQueryKeyFactory.searchJob('job1')
		});
	});

	it('cancelSearch invalidates the search-job query on success', async () => {
		mockInvalidate.mockClear();
		const m = cancelSearch() as unknown as {
			onSuccess: (d: unknown, jobId: string) => unknown;
		};
		await m.onSuccess({ status: 'ok', message: '' }, 'job1');
		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: DownloadQueryKeyFactory.searchJob('job1')
		});
	});

	it('key factory builds a stable search-job key', () => {
		expect(DownloadQueryKeyFactory.searchJob('j')).toEqual(['downloads', 'search', 'j']);
	});
});
