import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({
	loaded: true,
	configured: false,
	isAdmin: false
}));

vi.mock('$lib/stores/integration', () => ({
	integrationStore: {
		subscribe: (run: (v: { loaded: boolean; download_client: boolean }) => void) => {
			run({ loaded: h.loaded, download_client: h.configured });
			return () => {};
		},
		ensureLoaded: vi.fn()
	}
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: {
		get isAdmin() {
			return h.isAdmin;
		}
	}
}));

import DownloadsPage from './+page.svelte';

describe('/downloads page', () => {
	beforeEach(() => {
		h.loaded = true;
		h.configured = false;
		h.isAdmin = false;
	});

	it('shows the admin setup CTA when the client is not configured', async () => {
		h.isAdmin = true;
		render(DownloadsPage);
		await expect.element(page.getByText('Download client not configured')).toBeVisible();
		await expect
			.element(page.getByRole('link', { name: 'Configure Download Client' }))
			.toBeVisible();
	});

	it('shows a non-admin message (no CTA) when not configured', async () => {
		h.isAdmin = false;
		render(DownloadsPage);
		await expect
			.element(page.getByText('Contact your admin to configure the download client.'))
			.toBeVisible();
		await expect
			.element(page.getByRole('link', { name: 'Configure Download Client' }))
			.not.toBeInTheDocument();
	});

	it('shows a loading skeleton before integration status loads', async () => {
		h.loaded = false;
		const { container } = render(DownloadsPage);
		expect(container.querySelector('.skeleton')).not.toBeNull();
	});
});
