import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@tanstack/svelte-query', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@tanstack/svelte-query')>();
	return {
		...actual,
		createMutation: vi.fn((factory: () => Record<string, unknown>) => factory()),
		createQuery: vi.fn((factory: () => Record<string, unknown>) => factory())
	};
});

vi.mock('idb-keyval', () => ({
	get: vi.fn(),
	set: vi.fn(),
	del: vi.fn(),
	entries: vi.fn(async () => []),
	clear: vi.fn()
}));

vi.mock('$lib/api/client', () => ({
	api: { global: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { user: { id: 'userA' } as { id: string } | null, isAdmin: false },
	LAST_USER_ID_KEY: 'msr:last_user_id'
}));

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

import { api } from '$lib/api/client';
import { authStore } from '$lib/stores/authStore.svelte';
import { toastStore } from '$lib/stores/toast';
import { queryClient } from '../QueryClient';
import { FollowQueryKeyFactory } from './FollowQueryKeyFactory';
import { FOLLOW_ENDPOINTS } from './endpoints';
import {
	getFollowStatusQuery,
	getFollowedArtistsQuery,
	getNewReleasesQuery
} from './FollowQueries.svelte';
import { createSetAutoDownloadMutation, createSetFollowMutation } from './FollowMutations.svelte';
import type { FollowStatus } from './types';

const mockGet = vi.mocked(api.global.get);
const mockPut = vi.mocked(api.global.put);
const mockShow = vi.mocked(toastStore.show);

type Opts = {
	queryKey?: unknown;
	queryFn?: (ctx: { signal: AbortSignal }) => Promise<unknown>;
	mutationFn: (vars: unknown) => Promise<unknown>;
	onMutate?: (vars: unknown) => Promise<{ prev: FollowStatus }>;
	onSuccess?: (data: unknown, vars: unknown) => Promise<void> | void;
};

const MBID = 'artist-1';
const auth = authStore as unknown as { user: { id: string } | null; isAdmin: boolean };

beforeEach(() => {
	vi.clearAllMocks();
	auth.user = { id: 'userA' };
	auth.isAdmin = false;
	mockGet.mockResolvedValue({ followed: false, auto_download: false, auto_download_state: 'none' });
	mockPut.mockResolvedValue({ followed: true, auto_download: false, auto_download_state: 'none' });
	queryClient.clear();
});

describe('FollowQueryKeyFactory (AMU-5)', () => {
	it('scopes every key by userId and falls back to anon', () => {
		expect(FollowQueryKeyFactory.status(MBID, 'userA')).toEqual([
			'follow',
			'status',
			MBID,
			'userA'
		]);
		expect(FollowQueryKeyFactory.status(MBID, undefined)).toEqual([
			'follow',
			'status',
			MBID,
			'anon'
		]);
		expect(FollowQueryKeyFactory.artists('userA')).toEqual(['following', 'artists', 'userA']);
		expect(FollowQueryKeyFactory.newReleases('userA', 50, 0)).toEqual([
			'following',
			'new-releases',
			'userA',
			50,
			0
		]);
		expect(FollowQueryKeyFactory.status(MBID, 'userB')).not.toEqual(
			FollowQueryKeyFactory.status(MBID, 'userA')
		);
	});
});

describe('follow queries hit the right endpoints with user-scoped keys', () => {
	it('getFollowStatusQuery', async () => {
		const opts = getFollowStatusQuery(() => MBID) as unknown as Opts;
		expect(opts.queryKey).toEqual(['follow', 'status', MBID, 'userA']);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.status(MBID));
	});

	it('getFollowedArtistsQuery', async () => {
		const opts = getFollowedArtistsQuery() as unknown as Opts;
		expect(opts.queryKey).toEqual(['following', 'artists', 'userA']);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.followedArtists());
	});

	it('getNewReleasesQuery', async () => {
		const opts = getNewReleasesQuery(
			() => 24,
			() => 0
		) as unknown as Opts;
		expect(opts.queryKey).toEqual(['following', 'new-releases', 'userA', 24, 0]);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.newReleases(24, 0));
	});
});

describe('follow mutations', () => {
	it('setFollow PUTs { followed } to the follow endpoint', async () => {
		const m = createSetFollowMutation(() => MBID) as unknown as Opts;
		await m.mutationFn(true);
		expect(mockPut).toHaveBeenCalledWith(FOLLOW_ENDPOINTS.setFollow(MBID), { followed: true });
	});

	it('setAutoDownload PUTs { enabled } to the auto-download endpoint', async () => {
		const m = createSetAutoDownloadMutation(() => MBID) as unknown as Opts;
		await m.mutationFn(true);
		expect(mockPut).toHaveBeenCalledWith(FOLLOW_ENDPOINTS.autoDownload(MBID), { enabled: true });
	});

	it('non-admin auto-download optimistically goes pending (D3)', async () => {
		auth.isAdmin = false;
		const m = createSetAutoDownloadMutation(() => MBID) as unknown as Opts;
		await m.onMutate!(true);
		const cached = queryClient.getQueryData<FollowStatus>(
			FollowQueryKeyFactory.status(MBID, 'userA')
		);
		expect(cached?.auto_download).toBe(true);
		expect(cached?.auto_download_state).toBe('pending');
	});

	it('admin auto-download optimistically goes approved (D3)', async () => {
		auth.isAdmin = true;
		const m = createSetAutoDownloadMutation(() => MBID) as unknown as Opts;
		await m.onMutate!(true);
		const cached = queryClient.getQueryData<FollowStatus>(
			FollowQueryKeyFactory.status(MBID, 'userA')
		);
		expect(cached?.auto_download_state).toBe('approved');
	});

	it('shows the pending toast when the server confirms pending', async () => {
		const m = createSetAutoDownloadMutation(() => MBID) as unknown as Opts;
		await m.onSuccess!(
			{ followed: true, auto_download: true, auto_download_state: 'pending' },
			true
		);
		expect(mockShow).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'info', message: expect.stringContaining('admin') })
		);
	});

	it('does not toast when an admin is approved immediately', async () => {
		const m = createSetAutoDownloadMutation(() => MBID) as unknown as Opts;
		await m.onSuccess!(
			{ followed: true, auto_download: true, auto_download_state: 'approved' },
			true
		);
		expect(mockShow).not.toHaveBeenCalled();
	});
});
