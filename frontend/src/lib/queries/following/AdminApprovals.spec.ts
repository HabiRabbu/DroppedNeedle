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

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

import { api } from '$lib/api/client';
import { toastStore } from '$lib/stores/toast';
import { queryClient } from '../QueryClient';
import { FollowQueryKeyFactory } from './FollowQueryKeyFactory';
import { FOLLOW_ENDPOINTS } from './endpoints';
import { getAutoDownloadApprovalsQuery } from './AdminApprovalsQueries.svelte';
import {
	createApproveAutoDownloadMutation,
	createRejectAutoDownloadMutation
} from './AdminApprovalsMutations.svelte';

const mockGet = vi.mocked(api.global.get);
const mockPost = vi.mocked(api.global.post);
const mockShow = vi.mocked(toastStore.show);

type Opts = {
	queryKey?: unknown;
	enabled?: boolean;
	queryFn?: (ctx: { signal: AbortSignal }) => Promise<unknown>;
	mutationFn: (vars: unknown) => Promise<unknown>;
	onSuccess?: (data: unknown, vars: unknown) => Promise<void> | void;
};

const VARS = { userId: 'user-a', mbid: 'artist-1', artistName: 'Radiohead' };

beforeEach(() => {
	vi.clearAllMocks();
	mockGet.mockResolvedValue({ items: [], count: 0 });
	mockPost.mockResolvedValue({ success: true, message: 'ok' });
});

describe('admin auto-download approvals query', () => {
	it('uses the global admin key and hits the approvals endpoint', async () => {
		const opts = getAutoDownloadApprovalsQuery(() => true) as unknown as Opts;
		expect(opts.queryKey).toEqual(['following', 'admin-approvals']);
		expect(opts.enabled).toBe(true);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.adminApprovals());
	});

	it('is disabled for non-admins / inactive tab', () => {
		const opts = getAutoDownloadApprovalsQuery(() => false) as unknown as Opts;
		expect(opts.enabled).toBe(false);
	});
});

describe('admin approval mutations', () => {
	it('approve POSTs the approve endpoint and toasts + invalidates', async () => {
		const spy = vi.spyOn(queryClient, 'invalidateQueries');
		const m = createApproveAutoDownloadMutation() as unknown as Opts;
		await m.mutationFn(VARS);
		expect(mockPost.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.approve('user-a', 'artist-1'));
		await m.onSuccess!({ success: true, message: 'ok' }, VARS);
		expect(mockShow).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'success', message: expect.stringContaining('Radiohead') })
		);
		expect(spy.mock.calls[0][0]).toEqual(
			expect.objectContaining({ queryKey: FollowQueryKeyFactory.adminApprovals() })
		);
		spy.mockRestore();
	});

	it('reject POSTs the reject endpoint and toasts', async () => {
		const m = createRejectAutoDownloadMutation() as unknown as Opts;
		await m.mutationFn(VARS);
		expect(mockPost.mock.calls[0][0]).toBe(FOLLOW_ENDPOINTS.reject('user-a', 'artist-1'));
		await m.onSuccess!({ success: true, message: 'ok' }, VARS);
		expect(mockShow).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'info', message: expect.stringContaining('Radiohead') })
		);
	});
});
