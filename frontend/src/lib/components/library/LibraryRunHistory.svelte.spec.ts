import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { ScanRun } from '$lib/queries/library/LibraryOperationsTypes';

function run(overrides: Partial<ScanRun> = {}): ScanRun {
	return {
		id: 'run-safe-1',
		kind: 'incremental',
		trigger: 'automatic',
		state: 'completed',
		phase: 'reconciling',
		requested_by_user_id: null,
		aggregate_scope: 'root-1',
		queued_at: 100,
		started_at: 110,
		updated_at: 145,
		terminal_at: 145,
		resume_phase: null,
		requested_control: 'none',
		terminal_code: 'COMPLETED',
		coalesced_request_count: 0,
		row_revision: 2,
		event_revision: 3,
		counters: { discovered_count: 40, changed_count: 7, errored_count: 1 },
		phase_timings: { discovering: 10.5, indexing: 24.5 },
		...overrides
	};
}

const h = vi.hoisted(() => ({
	history: {
		data: { pages: [{ items: [] }] },
		isLoading: false,
		isError: false,
		hasNextPage: false,
		isFetchingNextPage: false,
		fetchNextPage: vi.fn()
	} as Record<string, unknown>,
	get: vi.fn(),
	toast: vi.fn(),
	anchorClick: vi.fn()
}));

vi.mock('$lib/queries/library/LibraryOperationQueries.svelte', () => ({
	getLibraryRunHistoryQuery: () => h.history
}));
vi.mock('$lib/api/client', () => ({ api: { global: { get: h.get } } }));
vi.mock('$lib/stores/toast', () => ({ toastStore: { show: h.toast } }));

import LibraryRunHistory from './LibraryRunHistory.svelte';

beforeEach(() => {
	vi.clearAllMocks();
	h.history = {
		data: { pages: [{ items: [run()] }] },
		isLoading: false,
		isError: false,
		hasNextPage: false,
		isFetchingNextPage: false,
		fetchNextPage: vi.fn()
	};
	vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:diagnostic');
	vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
	vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(h.anchorClick);
});

describe('LibraryRunHistory', () => {
	it('shows retained run counts, safe reason, and phase timings', async () => {
		render(LibraryRunHistory);
		await expect.element(page.getByText('7 changed · 1 errors')).toBeVisible();
		await expect.element(page.getByRole('cell', { name: '35s' })).toBeVisible();
		await page.getByText('Details').first().click();
		await expect.element(page.getByRole('dialog', { name: 'Run details' })).toBeVisible();
		await expect.element(page.getByText('Finished normally').first()).toBeVisible();
		await expect.element(page.getByText('discovering · 10.5s').first()).toBeVisible();
		await expect.element(page.getByText('indexing · 24.5s').first()).toBeVisible();
	});

	it('confirms redaction and honors the streamed safe filename', async () => {
		h.get.mockResolvedValue(
			new Response('{"safe":true}', {
				status: 200,
				headers: {
					'content-type': 'application/json',
					'content-disposition': 'attachment; filename="droppedneedle-library-run-opaque.json"'
				}
			})
		);
		render(LibraryRunHistory);
		await page.getByText('Details').first().click();
		await page.getByRole('button', { name: /Export diagnostics for run run-safe-1/ }).click();
		await expect
			.element(page.getByText(/excludes credentials, raw provider responses/))
			.toBeVisible();
		await page.getByRole('button', { name: 'Export report' }).click();
		expect(h.get).toHaveBeenCalledWith('/api/v1/library/scan-runs/run-safe-1/diagnostics', {
			raw: true
		});
		expect(h.anchorClick).toHaveBeenCalledOnce();
		expect(h.toast).toHaveBeenCalledWith({ message: 'Diagnostic report ready', type: 'success' });
	});

	it('uses fixed user-safe copy when an export fails', async () => {
		h.get.mockRejectedValue(new Error('/secret/path/provider-token'));
		render(LibraryRunHistory);
		await page.getByText('Details').first().click();
		await page.getByRole('button', { name: /Export diagnostics/ }).click();
		await page.getByRole('button', { name: 'Export report' }).click();
		expect(h.toast).toHaveBeenCalledWith({
			message: 'Could not prepare the diagnostic report',
			type: 'error'
		});
		expect(document.body.textContent).not.toContain('/secret/path');
	});

	it('shows three recent runs by default and keeps older audit history available', async () => {
		h.history = {
			data: {
				pages: [
					{
						items: [
							run({ id: 'run-5', aggregate_scope: 'scope-5' }),
							run({ id: 'run-4', aggregate_scope: 'scope-4' }),
							run({ id: 'run-3', aggregate_scope: 'scope-3' }),
							run({ id: 'run-2', aggregate_scope: 'scope-2' }),
							run({ id: 'run-1', aggregate_scope: 'scope-1' })
						]
					}
				]
			},
			isLoading: false,
			isError: false,
			hasNextPage: false,
			isFetchingNextPage: false,
			fetchNextPage: vi.fn()
		};
		render(LibraryRunHistory);

		await expect.element(page.getByText('scope-3').first()).toBeVisible();
		await expect.element(page.getByText('scope-2')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Show 2 older runs' }).click();
		await expect.element(page.getByText('scope-2').first()).toBeVisible();
		await expect.element(page.getByRole('button', { name: 'Show latest 3' })).toBeVisible();
	});
});
