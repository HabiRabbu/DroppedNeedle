import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ConnectAppsQueryKeyFactory } from './ConnectAppsQueryKeyFactory';

vi.mock('@tanstack/svelte-query', () => ({
	createMutation: vi.fn((factory: () => Record<string, unknown>) => factory())
}));

vi.mock('$lib/api/client', () => ({
	api: { global: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
}));

vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn()
}));

import { api } from '$lib/api/client';
import { createMutation } from '@tanstack/svelte-query';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';

const mockPut = vi.mocked(api.global.put);
const mockPost = vi.mocked(api.global.post);
const mockDelete = vi.mocked(api.global.delete);
const mockCreateMutation = vi.mocked(createMutation);
const mockInvalidate = vi.mocked(invalidateQueriesWithPersister);

beforeEach(() => vi.clearAllMocks());

function lastMutationOpts(): Record<string, unknown> {
	const calls = mockCreateMutation.mock.calls;
	return (calls[calls.length - 1][0] as unknown as () => Record<string, unknown>)();
}

describe('ConnectAppsQueryKeyFactory', () => {
	it('keys settings + app-passwords under the connect-apps prefix', () => {
		expect(ConnectAppsQueryKeyFactory.settings()).toEqual(['connect-apps', 'settings']);
		expect(ConnectAppsQueryKeyFactory.appPasswords()).toEqual(['connect-apps', 'app-passwords']);
	});
});

describe('saveConnectAppsSettings', () => {
	it('PUTs the settings and invalidates the settings key', async () => {
		mockPut.mockResolvedValue({});
		const { saveConnectAppsSettings } = await import('./ConnectAppsMutations.svelte');
		saveConnectAppsSettings();
		const opts = lastMutationOpts();
		await (opts.mutationFn as (v: unknown) => Promise<unknown>)({ subsonic_enabled: true });
		expect(mockPut).toHaveBeenCalledWith('/api/v1/connect-apps/settings', { subsonic_enabled: true });
		await (opts.onSuccess as () => Promise<unknown>)();
		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: ConnectAppsQueryKeyFactory.settings()
		});
	});
});

describe('createAppPassword', () => {
	it('POSTs {name} and invalidates the app-passwords list', async () => {
		mockPost.mockResolvedValue({ secret: 's', app_password: {} });
		const { createAppPassword } = await import('./ConnectAppsMutations.svelte');
		createAppPassword();
		const opts = lastMutationOpts();
		await (opts.mutationFn as (v: string) => Promise<unknown>)('Symfonium (phone)');
		expect(mockPost).toHaveBeenCalledWith('/api/v1/connect-apps/app-passwords', {
			name: 'Symfonium (phone)'
		});
		await (opts.onSuccess as () => Promise<unknown>)();
		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: ConnectAppsQueryKeyFactory.appPasswords()
		});
	});
});

describe('revokeAppPassword', () => {
	it('DELETEs by id and invalidates the app-passwords list', async () => {
		mockDelete.mockResolvedValue(undefined);
		const { revokeAppPassword } = await import('./ConnectAppsMutations.svelte');
		revokeAppPassword();
		const opts = lastMutationOpts();
		await (opts.mutationFn as (v: string) => Promise<unknown>)('ap-1');
		expect(mockDelete).toHaveBeenCalledWith('/api/v1/connect-apps/app-passwords/ap-1');
		await (opts.onSuccess as () => Promise<unknown>)();
		expect(mockInvalidate).toHaveBeenCalledWith({
			queryKey: ConnectAppsQueryKeyFactory.appPasswords()
		});
	});
});
