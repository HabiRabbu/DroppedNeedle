import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

// The dashboard pulls in queries / SSE / stores; stub it so this test covers the
// route shell (header + action buttons) in isolation.
vi.mock('$lib/components/library/LibraryDashboard.svelte', () => {
	const Comp = function () {};
	Comp.prototype = {};
	return { default: Comp };
});

import LibraryPage from './+page.svelte';

describe('library route page', () => {
	it('renders the Library header and subtitle', async () => {
		render(LibraryPage);
		await expect.element(page.getByRole('heading', { name: 'Library' })).toBeVisible();
		await expect.element(page.getByText('Your scanned music library')).toBeVisible();
	});

	it('links Listen to the Listening Room', async () => {
		render(LibraryPage);
		await expect
			.element(page.getByRole('link', { name: 'Listen' }))
			.toHaveAttribute('href', '/library/local');
	});
});
