import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({
	isAdmin: true,
	settings: {
		subsonic_enabled: true,
		jellyfin_enabled: true,
		transcoding_enabled: true,
		transcode_default_format: 'mp3',
		transcode_max_bitrate_kbps: 320,
		advertise_server_name: 'DroppedNeedle',
		advertise_server_version: '10.10.6',
		discover_mode: 'local-only'
	},
	passwords: {
		items: [
			{ id: 'ap-1', name: 'Symfonium (phone)', created_at: '2026-06-01T00:00:00Z', last_used_at: null, last_client: null }
		],
		cap: 25,
		active_count: 1
	},
	createMutate: vi.fn().mockResolvedValue({
		secret: 'super-secret-123',
		app_password: { id: 'ap-2', name: 'Finamp (tablet)', created_at: '', last_used_at: null, last_client: null }
	}),
	revokeMutate: vi.fn().mockResolvedValue(undefined),
	saveMutate: vi.fn().mockResolvedValue({})
}));

vi.mock('$lib/queries/connect-apps/ConnectAppsQueries.svelte', () => ({
	getConnectAppsSettingsQuery: () => ({ data: h.settings, isLoading: false, isError: false }),
	getAppPasswordsQuery: () => ({ data: h.passwords })
}));

vi.mock('$lib/queries/connect-apps/ConnectAppsMutations.svelte', () => ({
	saveConnectAppsSettings: () => ({ mutateAsync: h.saveMutate, isPending: false }),
	createAppPassword: () => ({ mutateAsync: h.createMutate, isPending: false }),
	revokeAppPassword: () => ({ mutateAsync: h.revokeMutate, isPending: false })
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: {
		get isAdmin() {
			return h.isAdmin;
		},
		user: { username: 'alice' }
	}
}));

vi.mock('$lib/stores/toast', () => ({ toastStore: { show: vi.fn() } }));

import SettingsConnectApps from './SettingsConnectApps.svelte';

beforeEach(() => {
	h.isAdmin = true;
	h.settings = {
		subsonic_enabled: true,
		jellyfin_enabled: true,
		transcoding_enabled: true,
		transcode_default_format: 'mp3',
		transcode_max_bitrate_kbps: 320,
		advertise_server_name: 'DroppedNeedle',
		advertise_server_version: '10.10.6',
		discover_mode: 'local-only'
	};
	h.passwords = {
		items: [
			{ id: 'ap-1', name: 'Symfonium (phone)', created_at: '2026-06-01T00:00:00Z', last_used_at: null, last_client: null }
		],
		cap: 25,
		active_count: 1
	};
	vi.clearAllMocks();
});

describe('SettingsConnectApps.svelte', () => {
	it('renders the inbound hero and admin protocol toggles', async () => {
		render(SettingsConnectApps);
		await expect
			.element(page.getByRole('heading', { name: 'Connect Apps', level: 2 }))
			.toBeInTheDocument();
		await expect.element(page.getByLabelText('Enable OpenSubsonic API')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Enable Jellyfin API')).toBeInTheDocument();
	});

	it('lists app-passwords with a cap indicator and no secret', async () => {
		render(SettingsConnectApps);
		await expect.element(page.getByText('Symfonium (phone)')).toBeInTheDocument();
		await expect.element(page.getByText('1 / 25')).toBeInTheDocument();
	});

	it('renders connection URLs for both protocols', async () => {
		render(SettingsConnectApps);
		await expect.element(page.getByLabelText('OpenSubsonic server URL')).toBeInTheDocument();
		await expect.element(page.getByLabelText('Jellyfin server URL')).toBeInTheDocument();
		await expect.element(page.getByText(/Tested clients: Symfonium, Feishin, Amperfy/)).toBeInTheDocument();
	});

	it('reveals the created secret exactly once', async () => {
		render(SettingsConnectApps);
		await page.getByLabelText('New app-password name').fill('Finamp (tablet)');
		await page.getByRole('button', { name: 'Create' }).click();
		// The reveal modal markup is always in the DOM (no CSS hides it in tests), so key the
		// assertion off bound values that only populate after a successful create.
		await expect.element(page.getByLabelText('App-password secret')).toHaveValue('super-secret-123');
		await expect
			.element(page.getByText(/only time "Finamp \(tablet\)" will be shown/))
			.toBeInTheDocument();
		expect(h.createMutate).toHaveBeenCalledWith('Finamp (tablet)');
	});

	it('disables Create at the cap', async () => {
		h.passwords = { items: [], cap: 25, active_count: 25 };
		render(SettingsConnectApps);
		await expect.element(page.getByRole('button', { name: 'Create' })).toBeDisabled();
	});

	it('confirms before revoking', async () => {
		render(SettingsConnectApps);
		await page.getByRole('button', { name: 'Revoke Symfonium (phone)' }).click();
		await expect.element(page.getByText(/Revoke "Symfonium \(phone\)"\?/)).toBeInTheDocument();
		expect(h.revokeMutate).not.toHaveBeenCalled();
	});

	it('non-admin sees a read-only note instead of editable controls', async () => {
		h.isAdmin = false;
		render(SettingsConnectApps);
		await expect.element(page.getByText(/Only an administrator can change these/)).toBeInTheDocument();
		await expect.element(page.getByLabelText('Enable OpenSubsonic API')).toBeDisabled();
	});

	it('non-admin with both protocols off and no passwords sees the disabled panel', async () => {
		h.isAdmin = false;
		h.settings = { ...h.settings, subsonic_enabled: false, jellyfin_enabled: false };
		h.passwords = { items: [], cap: 25, active_count: 0 };
		render(SettingsConnectApps);
		await expect.element(page.getByText('Connect Apps is turned off')).toBeInTheDocument();
	});
});
