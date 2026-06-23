import { describe, expect, it, vi, beforeEach } from 'vitest';

// Keep the real QueryClient/persister (we exercise the real cache reset below) but
// stub createQuery/createMutation so we can pull the options object straight out.
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
	api: { global: { get: vi.fn(), post: vi.fn(), put: vi.fn(), upload: vi.fn() } }
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { setUser: vi.fn(), clear: vi.fn(), user: null },
	LAST_USER_ID_KEY: 'msr:last_user_id'
}));

import { api } from '$lib/api/client';
import { authStore } from '$lib/stores/authStore.svelte';
import { clear as idbClear } from 'idb-keyval';
import {
	queryClient,
	resetQueryCacheForUserSwitch,
	setQueryDataWithPersister
} from '../QueryClient';
import { ProfileQueryKeyFactory } from './ProfileQueryKeyFactory';
import { PROFILE_ENDPOINTS } from './endpoints';
import { getProfileQuery } from './ProfileQuery.svelte';
import {
	createChangePasswordMutation,
	createSetPasswordMutation,
	createUpdateDisplayNameMutation,
	createUpdateEmailMutation,
	createUpdateUsernameMutation,
	createUploadAvatarMutation
} from './ProfileMutations.svelte';

const mockGet = vi.mocked(api.global.get);
const mockPost = vi.mocked(api.global.post);
const mockPut = vi.mocked(api.global.put);
const mockUpload = vi.mocked(api.global.upload);

const SESSION_USER = {
	id: 'userA',
	display_name: 'Alice',
	role: 'user',
	email: null,
	avatar_url: null,
	username: 'alice',
	username_display: 'alice',
	providers: ['local']
};

beforeEach(() => {
	vi.clearAllMocks();
	mockGet.mockResolvedValue({});
	mockPost.mockResolvedValue(SESSION_USER);
	mockPut.mockResolvedValue(SESSION_USER);
	mockUpload.mockResolvedValue(SESSION_USER);
});

type Opts = {
	queryKey?: unknown;
	queryFn?: (ctx: { signal: AbortSignal }) => Promise<unknown>;
	mutationFn: (vars: unknown) => Promise<unknown>;
	onSuccess: (user: unknown) => Promise<void> | void;
};

describe('ProfileQueryKeyFactory', () => {
	it('scopes the profile key by userId (AMU-5)', () => {
		expect(ProfileQueryKeyFactory.profile('userA')).toEqual(['profile', 'userA']);
		expect(ProfileQueryKeyFactory.profile('userB')).not.toEqual(
			ProfileQueryKeyFactory.profile('userA')
		);
	});
});

describe('getProfileQuery', () => {
	it('builds a userId-scoped key and fetches /api/v1/profile', async () => {
		const opts = getProfileQuery('userA') as unknown as Opts;
		expect(opts.queryKey).toEqual(['profile', 'userA']);
		await opts.queryFn!({ signal: new AbortController().signal });
		expect(mockGet.mock.calls[0][0]).toBe(PROFILE_ENDPOINTS.get);
	});
});

describe('profile mutations hit the correct endpoints', () => {
	it('display name -> PUT /profile', async () => {
		const m = createUpdateDisplayNameMutation('userA') as unknown as Opts;
		await m.mutationFn({ display_name: 'Bob' });
		expect(mockPut).toHaveBeenCalledWith(PROFILE_ENDPOINTS.update, { display_name: 'Bob' });
	});

	it('username -> PUT /profile/username', async () => {
		const m = createUpdateUsernameMutation('userA') as unknown as Opts;
		await m.mutationFn({ username: 'bob' });
		expect(mockPut).toHaveBeenCalledWith(PROFILE_ENDPOINTS.updateUsername, { username: 'bob' });
	});

	it('email -> PUT /profile/email', async () => {
		const m = createUpdateEmailMutation('userA') as unknown as Opts;
		await m.mutationFn({ email: null });
		expect(mockPut).toHaveBeenCalledWith(PROFILE_ENDPOINTS.updateEmail, { email: null });
	});

	it('change password -> POST /profile/password', async () => {
		const m = createChangePasswordMutation('userA') as unknown as Opts;
		await m.mutationFn({ current_password: 'a', new_password: 'b' });
		expect(mockPost).toHaveBeenCalledWith(PROFILE_ENDPOINTS.changePassword, {
			current_password: 'a',
			new_password: 'b'
		});
	});

	it('set password -> POST /profile/set-password', async () => {
		const m = createSetPasswordMutation('userA') as unknown as Opts;
		await m.mutationFn({ new_password: 'b' });
		expect(mockPost).toHaveBeenCalledWith(PROFILE_ENDPOINTS.setPassword, { new_password: 'b' });
	});

	it('avatar -> POST /profile/avatar as multipart form data', async () => {
		const m = createUploadAvatarMutation('userA') as unknown as Opts;
		await m.mutationFn(new File(['x'], 'a.png', { type: 'image/png' }));
		expect(mockUpload.mock.calls[0][0]).toBe(PROFILE_ENDPOINTS.avatarUpload);
		expect(mockUpload.mock.calls[0][1]).toBeInstanceOf(FormData);
	});
});

describe('mutation onSuccess', () => {
	it('syncs authStore and invalidates the user-scoped profile key', async () => {
		const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
		const m = createUpdateUsernameMutation('userA') as unknown as Opts;

		await m.onSuccess(SESSION_USER);

		expect(authStore.setUser).toHaveBeenCalledTimes(1);
		expect(invalidateSpy).toHaveBeenCalledTimes(1);
		expect(invalidateSpy.mock.calls[0][0]).toEqual(
			expect.objectContaining({ queryKey: ['profile', 'userA'] })
		);
		invalidateSpy.mockRestore();
	});
});

describe('resetQueryCacheForUserSwitch (AMU-5)', () => {
	it('empties the in-memory client AND the persisted IndexedDB store', async () => {
		await setQueryDataWithPersister(['profile', 'userA'], { display_name: 'leaked' });
		expect(queryClient.getQueryData(['profile', 'userA'])).toBeDefined();

		await resetQueryCacheForUserSwitch();

		expect(queryClient.getQueryData(['profile', 'userA'])).toBeUndefined();
		expect(idbClear).toHaveBeenCalled();
	});
});
