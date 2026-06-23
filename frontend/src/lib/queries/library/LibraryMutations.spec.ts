import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@tanstack/svelte-query', () => ({
	createMutation: vi.fn((factory: () => Record<string, unknown>) => factory())
}));

vi.mock('$lib/api/client', () => ({
	api: { global: { post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
}));

vi.mock('../QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn()
}));

import { api } from '$lib/api/client';
import {
	startLibraryScan,
	startForceLibraryScan,
	saveLibraryScanSchedule
} from './LibraryMutations.svelte';

const mockPost = vi.mocked(api.global.post);
const mockPut = vi.mocked(api.global.put);

beforeEach(() => {
	vi.clearAllMocks();
	mockPost.mockResolvedValue({});
	mockPut.mockResolvedValue({});
});

async function runMutation(m: unknown) {
	await (m as { mutationFn: () => Promise<unknown> }).mutationFn();
}

describe('library scan mutations', () => {
	it('startLibraryScan posts to scan/start without the force flag', async () => {
		await runMutation(startLibraryScan());
		expect(mockPost.mock.calls[0][0]).toBe('/api/v1/library/scan/start');
	});

	it('startForceLibraryScan posts to scan/start with force=true', async () => {
		await runMutation(startForceLibraryScan());
		expect(mockPost.mock.calls[0][0]).toBe('/api/v1/library/scan/start?force=true');
	});

	it('saveLibraryScanSchedule puts to the schedule endpoint', async () => {
		const m = saveLibraryScanSchedule();
		await (m as unknown as { mutationFn: (s: unknown) => Promise<unknown> }).mutationFn({
			scan_frequency: '6hr',
			daily_scan_time: '03:00',
			last_scan: null,
			last_scan_success: true
		});
		expect(mockPut.mock.calls[0][0]).toBe('/api/v1/settings/library/schedule');
	});
});
