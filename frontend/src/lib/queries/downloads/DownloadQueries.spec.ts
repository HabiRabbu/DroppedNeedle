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

vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn()
}));

const { mockToast } = vi.hoisted(() => ({ mockToast: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: (...args: unknown[]) => mockToast(...args) }
}));

import { getDownloadsQueryOptions } from './DownloadQueries.svelte';
import {
	cancelDownload,
	requestAlbum,
	requestTrack,
	retryDownload
} from './DownloadMutations.svelte';

describe('download queue queries', () => {
	it('the downloads list query hits /api/v1/downloads', async () => {
		const opts = getDownloadsQueryOptions() as { queryFn: (a: unknown) => unknown };
		await opts.queryFn({ signal: undefined });
		expect(String(mockGet.mock.calls.at(-1)?.[0])).toContain('/api/v1/downloads');
	});

	it('requestAlbum posts to /requests/new with the mapped body', async () => {
		const m = requestAlbum() as unknown as { mutationFn: (i: unknown) => unknown };
		await m.mutationFn({
			release_group_mbid: 'rg',
			artist_name: 'A',
			album_title: 'B',
			year: 2000
		});
		const call = mockPost.mock.calls.at(-1);
		expect(String(call?.[0])).toContain('/requests/new');
		expect(call?.[1]).toMatchObject({ musicbrainz_id: 'rg', artist: 'A', album: 'B', year: 2000 });
	});

	it('requestTrack posts to /tracks/{recording_mbid}/request', async () => {
		const m = requestTrack() as unknown as { mutationFn: (i: unknown) => unknown };
		await m.mutationFn({ recording_mbid: 'rec', artist_name: 'A', track_title: 'T' });
		expect(String(mockPost.mock.calls.at(-1)?.[0])).toContain('/tracks/rec/request');
	});

	it('cancelDownload posts to /downloads/{id}/cancel', async () => {
		const m = cancelDownload() as unknown as { mutationFn: (i: string) => unknown };
		await m.mutationFn('t1');
		expect(String(mockPost.mock.calls.at(-1)?.[0])).toContain('/downloads/t1/cancel');
	});

	it('retryDownload posts to /downloads/{id}/retry', async () => {
		const m = retryDownload() as unknown as { mutationFn: (i: string) => unknown };
		await m.mutationFn('t1');
		expect(String(mockPost.mock.calls.at(-1)?.[0])).toContain('/downloads/t1/retry');
	});

	it('requestAlbum shows the "searching" toast for a pending status', () => {
		mockToast.mockClear();
		const m = requestAlbum() as unknown as { onSuccess: (d: unknown) => unknown };
		m.onSuccess({ success: true, message: '', musicbrainz_id: 'rg', status: 'pending' });
		expect(mockToast).toHaveBeenCalledWith(
			expect.objectContaining({ message: expect.stringContaining('searching') })
		);
	});

	it('requestAlbum shows the approval toast for awaiting_approval', () => {
		mockToast.mockClear();
		const m = requestAlbum() as unknown as { onSuccess: (d: unknown) => unknown };
		m.onSuccess({ success: true, message: '', musicbrainz_id: 'rg', status: 'awaiting_approval' });
		expect(mockToast).toHaveBeenCalledWith(
			expect.objectContaining({ message: expect.stringContaining('approval') })
		);
	});

	it('the key factory builds stable keys', () => {
		expect(DownloadQueryKeyFactory.tasks()).toEqual(['downloads', 'tasks']);
		expect(DownloadQueryKeyFactory.quarantine()).toEqual(['downloads', 'quarantine']);
	});
});
