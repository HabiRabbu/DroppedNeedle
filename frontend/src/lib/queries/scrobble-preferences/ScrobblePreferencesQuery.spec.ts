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
	api: { global: { get: vi.fn(), put: vi.fn() } }
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { user: { id: 'userA' } as { id: string } | null },
	LAST_USER_ID_KEY: 'msr:last_user_id'
}));

import { api } from '$lib/api/client';
import { authStore } from '$lib/stores/authStore.svelte';
import { queryClient } from '../QueryClient';
import { ScrobblePreferencesQueryKeyFactory } from './ScrobblePreferencesQueryKeyFactory';
import { SCROBBLE_PREFERENCES_ENDPOINTS } from './endpoints';
import { getScrobblePreferencesQuery } from './ScrobblePreferencesQuery.svelte';
import { createUpdateScrobblePreferencesMutation } from './ScrobblePreferencesMutations.svelte';

const mockGet = vi.mocked(api.global.get);
const mockPut = vi.mocked(api.global.put);

type Opts = {
	queryKey?: unknown;
	queryFn?: (ctx: { signal: AbortSignal }) => Promise<unknown>;
	mutationFn: (vars: unknown) => Promise<unknown>;
	onSuccess?: (data: unknown) => Promise<void> | void;
};

beforeEach(() => {
	vi.clearAllMocks();
	(authStore as { user: { id: string } | null }).user = { id: 'userA' };
	mockGet.mockResolvedValue({
		scrobble_to_lastfm: false,
		scrobble_to_listenbrainz: false,
		primary_music_source: 'listenbrainz'
	});
	mockPut.mockResolvedValue({});
});

describe('ScrobblePreferencesQueryKeyFactory (AMU-5)', () => {
	it('scopes the key by userId', () => {
		expect(ScrobblePreferencesQueryKeyFactory.get('userA')).toEqual([
			'me',
			'scrobble-preferences',
			'userA'
		]);
		expect(ScrobblePreferencesQueryKeyFactory.get('userB')).not.toEqual(
			ScrobblePreferencesQueryKeyFactory.get('userA')
		);
	});
});

describe('getScrobblePreferencesQuery', () => {
	it('builds a userId-scoped key and fetches /me/scrobble-preferences', async () => {
		const opts = getScrobblePreferencesQuery() as unknown as Opts;
		expect(opts.queryKey).toEqual(['me', 'scrobble-preferences', 'userA']);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(SCROBBLE_PREFERENCES_ENDPOINTS.get);
	});
});

describe('update scrobble preferences', () => {
	it('PUTs the partial update', async () => {
		const m = createUpdateScrobblePreferencesMutation() as unknown as Opts;
		await m.mutationFn({ scrobble_to_lastfm: true });
		expect(mockPut).toHaveBeenCalledWith(SCROBBLE_PREFERENCES_ENDPOINTS.update, {
			scrobble_to_lastfm: true
		});
	});

	it('onSuccess invalidates the user-scoped key', async () => {
		const spy = vi.spyOn(queryClient, 'invalidateQueries');
		const m = createUpdateScrobblePreferencesMutation() as unknown as Opts;
		await m.onSuccess!({});
		expect(spy.mock.calls[0][0]).toEqual(
			expect.objectContaining({ queryKey: ['me', 'scrobble-preferences', 'userA'] })
		);
		spy.mockRestore();
	});
});
