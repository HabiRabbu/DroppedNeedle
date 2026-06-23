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
	authStore: { user: { id: 'userA' } as { id: string } | null },
	LAST_USER_ID_KEY: 'msr:last_user_id'
}));

import { api } from '$lib/api/client';
import { authStore } from '$lib/stores/authStore.svelte';
import { queryClient } from '../QueryClient';
import { ConnectionsQueryKeyFactory } from './ConnectionsQueryKeyFactory';
import { CONNECTIONS_ENDPOINTS } from './endpoints';
import { getConnectionsQuery } from './ConnectionsQuery.svelte';
import {
	createConnectListenBrainzMutation,
	createDisconnectMutation,
	createLastFmExchangeSessionMutation,
	createLastFmRequestTokenMutation
} from './ConnectionsMutations.svelte';

const mockGet = vi.mocked(api.global.get);
const mockPost = vi.mocked(api.global.post);
const mockPut = vi.mocked(api.global.put);
const mockDelete = vi.mocked(api.global.delete);

type Opts = {
	queryKey?: unknown;
	queryFn?: (ctx: { signal: AbortSignal }) => Promise<unknown>;
	mutationFn: (vars: unknown) => Promise<unknown>;
	onSuccess?: (data: unknown) => Promise<void> | void;
};

beforeEach(() => {
	vi.clearAllMocks();
	(authStore as { user: { id: string } | null }).user = { id: 'userA' };
	mockGet.mockResolvedValue({ connections: [] });
	mockPost.mockResolvedValue({});
	mockPut.mockResolvedValue({});
	mockDelete.mockResolvedValue({ service: 'lastfm', deleted: true });
});

describe('ConnectionsQueryKeyFactory (AMU-5)', () => {
	it('scopes the key by userId and falls back to anon', () => {
		expect(ConnectionsQueryKeyFactory.list('userA')).toEqual(['me', 'connections', 'userA']);
		expect(ConnectionsQueryKeyFactory.list(undefined)).toEqual(['me', 'connections', 'anon']);
		expect(ConnectionsQueryKeyFactory.list('userB')).not.toEqual(
			ConnectionsQueryKeyFactory.list('userA')
		);
	});
});

describe('getConnectionsQuery', () => {
	it('builds a userId-scoped key and fetches /me/connections', async () => {
		const opts = getConnectionsQuery() as unknown as Opts;
		expect(opts.queryKey).toEqual(['me', 'connections', 'userA']);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(CONNECTIONS_ENDPOINTS.list);
	});

	it('does not leak across a user switch (key re-derives from authStore)', () => {
		expect((getConnectionsQuery() as unknown as Opts).queryKey).toEqual([
			'me',
			'connections',
			'userA'
		]);
		(authStore as { user: { id: string } | null }).user = { id: 'userB' };
		expect((getConnectionsQuery() as unknown as Opts).queryKey).toEqual([
			'me',
			'connections',
			'userB'
		]);
	});
});

describe('connection mutations hit the correct endpoints', () => {
	it('lastfm request token -> POST', async () => {
		const m = createLastFmRequestTokenMutation() as unknown as Opts;
		await m.mutationFn(undefined);
		expect(mockPost.mock.calls[0][0]).toBe(CONNECTIONS_ENDPOINTS.lastfmAuthToken);
	});

	it('lastfm exchange session -> POST with token', async () => {
		const m = createLastFmExchangeSessionMutation() as unknown as Opts;
		await m.mutationFn('tok-1');
		expect(mockPost).toHaveBeenCalledWith(CONNECTIONS_ENDPOINTS.lastfmAuthSession, {
			token: 'tok-1'
		});
	});

	it('connect listenbrainz -> PUT with token + username', async () => {
		const m = createConnectListenBrainzMutation() as unknown as Opts;
		await m.mutationFn({ user_token: 'lb', username: 'alice' });
		expect(mockPut).toHaveBeenCalledWith(CONNECTIONS_ENDPOINTS.listenbrainz, {
			user_token: 'lb',
			username: 'alice'
		});
	});

	it('disconnect -> DELETE /me/connections/{service}', async () => {
		const m = createDisconnectMutation() as unknown as Opts;
		await m.mutationFn('lastfm');
		expect(mockDelete.mock.calls[0][0]).toBe(CONNECTIONS_ENDPOINTS.connection('lastfm'));
	});
});

describe('mutation onSuccess invalidates the user-scoped key', () => {
	it('disconnect invalidates ["me","connections","userA"]', async () => {
		const spy = vi.spyOn(queryClient, 'invalidateQueries');
		const m = createDisconnectMutation() as unknown as Opts;
		await m.onSuccess!({ service: 'lastfm', deleted: true });
		expect(spy.mock.calls[0][0]).toEqual(
			expect.objectContaining({ queryKey: ['me', 'connections', 'userA'] })
		);
		spy.mockRestore();
	});
});
