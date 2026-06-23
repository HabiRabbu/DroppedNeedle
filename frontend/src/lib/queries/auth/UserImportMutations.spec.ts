import { describe, expect, it, vi, beforeEach } from 'vitest';
import { AuthQueryKeyFactory } from './AuthQueryKeyFactory';
import { AUTH_ENDPOINTS } from './endpoints';

vi.mock('@tanstack/svelte-query', () => ({
	createMutation: vi.fn((factory: () => Record<string, unknown>) => factory()),
	createQuery: vi.fn((factory: () => Record<string, unknown>) => factory())
}));

vi.mock('$lib/api/client', () => ({
	api: {
		get: vi.fn(),
		post: vi.fn()
	}
}));

vi.mock('../QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn()
}));

import { api } from '$lib/api/client';
import { createMutation, createQuery } from '@tanstack/svelte-query';
import { invalidateQueriesWithPersister } from '../QueryClient';

const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);
const mockCreateMutation = vi.mocked(createMutation);
const mockCreateQuery = vi.mocked(createQuery);
const mockInvalidate = vi.mocked(invalidateQueriesWithPersister);

beforeEach(() => {
	vi.clearAllMocks();
});

function lastMutationOpts(): Record<string, unknown> {
	const calls = mockCreateMutation.mock.calls;
	const factory = calls[calls.length - 1][0] as unknown as () => Record<string, unknown>;
	return factory();
}

function lastQueryOpts(): Record<string, unknown> {
	const calls = mockCreateQuery.mock.calls;
	const factory = calls[calls.length - 1][0] as unknown as () => Record<string, unknown>;
	return factory();
}

describe('AuthQueryKeyFactory.importCandidates', () => {
	it('keys by provider under the auth prefix', () => {
		expect(AuthQueryKeyFactory.importCandidates('plex')).toEqual(['auth', 'import', 'plex']);
	});
});

describe('createImportUsersMutation', () => {
	it('posts provider + uids to the import endpoint via the authenticated api', async () => {
		mockPost.mockResolvedValue({ imported: [], linked: [], skipped: [], total_imported: 0 });
		const { createImportUsersMutation } = await import('./UserImportMutations.svelte');
		createImportUsersMutation();

		const mutationFn = lastMutationOpts().mutationFn as (v: unknown) => Promise<unknown>;
		await mutationFn({ provider: 'jellyfin', provider_uids: ['jf-1', 'jf-2'] });

		expect(mockPost).toHaveBeenCalledWith(AUTH_ENDPOINTS.adminImport, {
			provider: 'jellyfin',
			provider_uids: ['jf-1', 'jf-2']
		});
	});

	it('onSuccess invalidates the importCandidates key for the imported provider', async () => {
		const { createImportUsersMutation } = await import('./UserImportMutations.svelte');
		createImportUsersMutation();

		const onSuccess = lastMutationOpts().onSuccess as (r: unknown, v: unknown) => unknown;
		await onSuccess(
			{ imported: [], linked: [], skipped: [], total_imported: 0 },
			{ provider: 'plex', provider_uids: [] }
		);

		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: AuthQueryKeyFactory.importCandidates('plex')
		});
	});
});

describe('getImportCandidatesQuery', () => {
	it('keys + hits the right endpoint per provider via authenticated api.get', async () => {
		mockGet.mockResolvedValue({ users: [] });
		const { getImportCandidatesQuery } = await import('./ImportCandidatesQuery.svelte');
		getImportCandidatesQuery(
			() => 'plex',
			() => true
		);

		const opts = lastQueryOpts();
		expect(opts.queryKey).toEqual(AuthQueryKeyFactory.importCandidates('plex'));
		expect(opts.enabled).toBe(true);

		const queryFn = opts.queryFn as (ctx: { signal: AbortSignal }) => Promise<unknown>;
		await queryFn({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(AUTH_ENDPOINTS.adminImportPlex);
	});

	it('is gated by the enabled getter (disabled while the picker is closed)', async () => {
		const { getImportCandidatesQuery } = await import('./ImportCandidatesQuery.svelte');
		getImportCandidatesQuery(
			() => 'jellyfin',
			() => false
		);

		const opts = lastQueryOpts();
		expect(opts.enabled).toBe(false);
		expect(opts.queryKey).toEqual(AuthQueryKeyFactory.importCandidates('jellyfin'));
	});
});
