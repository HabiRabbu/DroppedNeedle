import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { ServiceHealthItem } from '$lib/types';

vi.mock('$env/dynamic/public', () => ({ env: { PUBLIC_API_URL: '' } }));

const queryState = vi.hoisted(() => ({ data: { degraded: [] as ServiceHealthItem[] } }));
vi.mock('$lib/queries/system/SystemHealthQuery.svelte', () => ({
	getSystemHealthQuery: () => queryState
}));

const toast = vi.hoisted(() => ({ show: vi.fn() }));
vi.mock('$lib/stores/toast', () => ({ toastStore: toast }));

import ServiceHealthIndicator from './ServiceHealthIndicator.svelte';

describe('ServiceHealthIndicator', () => {
	it('is invisible when nothing is degraded', async () => {
		queryState.data = { degraded: [] };
		const { container } = render(ServiceHealthIndicator);
		expect(container.querySelector('button')).toBeNull();
	});

	it('shows the dot, toasts once, and reveals details on click', async () => {
		toast.show.mockClear();
		queryState.data = {
			degraded: [
				{
					service: 'listenbrainz',
					capability: 'popularity',
					severity: 'degraded',
					message: "ListenBrainz's popularity data is temporarily unavailable.",
					fallback: 'lastfm',
					degraded_seconds: 120
				}
			]
		};

		render(ServiceHealthIndicator);

		// first-time toast fired
		await vi.waitFor(() => expect(toast.show).toHaveBeenCalledTimes(1));

		// dot is visible; clicking opens the detail popover with the friendly names
		await page.getByRole('button', { name: /service status/i }).click();
		await expect.element(page.getByText('ListenBrainz', { exact: true })).toBeVisible();
		await expect.element(page.getByText(/Using .*Last\.fm.* instead/i)).toBeVisible();
	});
});
