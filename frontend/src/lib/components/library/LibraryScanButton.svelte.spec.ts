import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const h = vi.hoisted(() => ({
	statusQuery: { data: { status: 'idle' } } as { data: Record<string, unknown> | undefined },
	mutateAsync: vi.fn(),
	goto: vi.fn()
}));

vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryScanStatusQuery: () => h.statusQuery
}));

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	startLibraryScan: () => ({ mutateAsync: h.mutateAsync, isPending: false })
}));

vi.mock('$lib/stores/toast', () => ({ toastStore: { show: vi.fn() } }));
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => h.goto(...args) }));

import LibraryScanButton from './LibraryScanButton.svelte';

describe('LibraryScanButton.svelte', () => {
	beforeEach(() => {
		h.statusQuery = { data: { status: 'idle' } };
		h.mutateAsync = vi.fn();
		h.goto = vi.fn();
	});

	it('shows "Start scan" and starts a scan when idle', async () => {
		render(LibraryScanButton);
		const btn = page.getByRole('button', { name: 'Start scan' });
		await expect.element(btn).toBeEnabled();
		await btn.click();
		expect(h.mutateAsync).toHaveBeenCalled();
	});

	it('shows a disabled "Scanning…" state while a scan is running', async () => {
		h.statusQuery = { data: { status: 'scanning' } };
		render(LibraryScanButton);
		const btn = page.getByRole('button', { name: 'Scanning…' });
		await expect.element(btn).toBeVisible();
		await expect.element(btn).toBeDisabled();
	});

	it('routes to settings instead of scanning when no path is configured', async () => {
		render(LibraryScanButton, {
			props: { hasPath: false }
		} as Parameters<typeof render<typeof LibraryScanButton>>[1]);
		await page.getByRole('button', { name: 'Start scan' }).click();
		expect(h.mutateAsync).not.toHaveBeenCalled();
		expect(h.goto).toHaveBeenCalled();
	});
});
