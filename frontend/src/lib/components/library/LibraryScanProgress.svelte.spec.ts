import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { LibraryScanState } from '$lib/queries/library/LibrarySSE.svelte';

// The banner combines a polling status query, an SSE stream rune, a cancel
// mutation and the auth store. Stub each so the component renders deterministically
// without a QueryClientProvider / EventSource.
const idleSse: LibraryScanState = {
	status: 'idle',
	processed: 0,
	total: 0,
	matched: 0,
	unmatched: 0,
	errorMessage: null,
	warning: null,
	finalizing: null
};

function makeReactiveScan() {
	let started = 0;
	let running = false;
	let state = $state<LibraryScanState>({ ...idleSse });
	return {
		get state() {
			return state;
		},
		get startCount() {
			return started;
		},
		start: () => {
			if (running) return;
			running = true;
			started += 1;
			state = { ...state, status: 'scanning' };
		},
		stop: () => {
			running = false;
		}
	};
}

const h = vi.hoisted(() => ({
	statusQuery: { data: { status: 'idle' } } as { data: Record<string, unknown> | undefined },
	scan: {
		state: {
			status: 'idle',
			processed: 0,
			total: 0,
			matched: 0,
			unmatched: 0,
			errorMessage: null
		} as Record<string, unknown>,
		start: vi.fn(),
		stop: vi.fn()
	},
	isAdmin: true,
	cancelMutate: vi.fn()
}));

vi.mock('$lib/queries/library/LibraryQueries.svelte', () => ({
	getLibraryScanStatusQuery: () => h.statusQuery
}));

vi.mock('$lib/queries/library/LibrarySSE.svelte', () => ({
	createLibraryScanStream: () => h.scan
}));

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	cancelLibraryScan: () => ({ mutateAsync: h.cancelMutate, isPending: false })
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: {
		get isAdmin() {
			return h.isAdmin;
		}
	}
}));

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

import LibraryScanProgress from './LibraryScanProgress.svelte';

describe('LibraryScanProgress.svelte', () => {
	beforeEach(() => {
		h.statusQuery = { data: { status: 'idle' } };
		h.scan = { state: { ...idleSse }, start: vi.fn(), stop: vi.fn() };
		h.isAdmin = true;
		h.cancelMutate = vi.fn();
	});

	it('renders nothing when no scan is active', async () => {
		h.statusQuery = { data: { status: 'idle' } };
		render(LibraryScanProgress);
		await expect.element(page.getByText('Scanning library')).not.toBeInTheDocument();
	});

	it('shows live progress while a scan is running', async () => {
		h.statusQuery = {
			data: { status: 'scanning', processed_files: 4, total_files: 10, matched_files: 3 }
		};
		render(LibraryScanProgress);
		await expect.element(page.getByText('Scanning library')).toBeVisible();
		await expect.element(page.getByText('4 of 10 files')).toBeVisible();
		expect(h.scan.start).toHaveBeenCalled();
	});

	it('shows the admin Cancel button while scanning and triggers the cancel mutation', async () => {
		h.statusQuery = { data: { status: 'scanning', processed_files: 1, total_files: 10 } };
		render(LibraryScanProgress);
		await page.getByRole('button', { name: 'Cancel' }).click();
		expect(h.cancelMutate).toHaveBeenCalled();
	});

	it('hides the Cancel button for non-admins', async () => {
		h.statusQuery = { data: { status: 'scanning', processed_files: 1, total_files: 10 } };
		h.isAdmin = false;
		render(LibraryScanProgress);
		await expect.element(page.getByText('Scanning library')).toBeVisible();
		await expect.element(page.getByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
	});

	it('opens the live stream exactly once while scanning (no self-invalidating loop)', async () => {
		const reactiveScan = makeReactiveScan();
		h.scan = reactiveScan as unknown as typeof h.scan;
		h.statusQuery = { data: { status: 'scanning', processed_files: 1, total_files: 10 } };

		render(LibraryScanProgress);
		await expect.element(page.getByText('Scanning library')).toBeVisible();

		expect(reactiveScan.startCount).toBe(1);
	});
});
