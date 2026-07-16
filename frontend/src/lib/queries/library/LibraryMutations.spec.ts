import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@tanstack/svelte-query', () => ({
	createMutation: vi.fn((factory: () => Record<string, unknown>) => factory())
}));

vi.mock('$lib/api/client', () => ({
	api: { global: { post: vi.fn(), put: vi.fn(), delete: vi.fn() } }
}));

const { mockRemoveMbid } = vi.hoisted(() => ({ mockRemoveMbid: vi.fn() }));

vi.mock('$lib/stores/library', () => ({
	libraryStore: { removeMbid: mockRemoveMbid }
}));

vi.mock('../QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn().mockResolvedValue(undefined),
	setQueryDataWithPersister: vi.fn().mockResolvedValue(undefined)
}));

import { api } from '$lib/api/client';
import { removeLibraryAlbum, saveLibraryScanSchedule } from './LibraryMutations.svelte';
import { invalidateQueriesWithPersister, setQueryDataWithPersister } from '../QueryClient';

const mockPost = vi.mocked(api.global.post);
const mockPut = vi.mocked(api.global.put);
const mockDelete = vi.mocked(api.global.delete);

beforeEach(() => {
	vi.clearAllMocks();
	mockPost.mockResolvedValue({});
	mockPut.mockResolvedValue({});
	mockDelete.mockResolvedValue({});
});

describe('album removal mutation', () => {
	it('clears exact membership and invalidates every affected cache tree', async () => {
		const result = {
			success: true,
			album_mbid: 'rg-1',
			removed_mbids: ['release-1', 'rg-1'],
			artist_removed: false,
			artist_name: null
		};
		mockDelete.mockResolvedValueOnce(result);
		const mutation = removeLibraryAlbum() as unknown as {
			mutationFn: (mbid: string) => Promise<typeof result>;
			onSuccess: (data: typeof result, mbid: string) => Promise<void>;
		};

		const data = await mutation.mutationFn('release-1');
		await mutation.onSuccess(data, 'release-1');

		expect(mockDelete).toHaveBeenCalledWith('/api/v1/library/album/release-1?delete_files=true');
		expect(mockRemoveMbid).toHaveBeenCalledWith('release-1');
		expect(mockRemoveMbid).toHaveBeenCalledWith('rg-1');
		expect(setQueryDataWithPersister).toHaveBeenCalledWith(
			['library', 'album', 'release-1'],
			expect.any(Function)
		);
		expect(invalidateQueriesWithPersister).toHaveBeenCalledTimes(5);
	});

	it('does not report cache housekeeping failures as removal failures', async () => {
		const result = {
			success: true,
			album_mbid: 'rg-1',
			removed_mbids: ['rg-1'],
			artist_removed: false,
			artist_name: null
		};
		mockDelete.mockResolvedValueOnce(result);
		vi.mocked(setQueryDataWithPersister).mockRejectedValueOnce(new Error('IndexedDB unavailable'));
		vi.mocked(invalidateQueriesWithPersister).mockRejectedValueOnce(new Error('refresh failed'));
		const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const mutation = removeLibraryAlbum() as unknown as {
			mutationFn: (mbid: string) => Promise<typeof result>;
			onSuccess: (data: typeof result, mbid: string) => Promise<void>;
		};

		const data = await mutation.mutationFn('rg-1');

		await expect(mutation.onSuccess(data, 'rg-1')).resolves.toBeUndefined();
		expect(invalidateQueriesWithPersister).toHaveBeenCalledTimes(5);
		expect(consoleError).toHaveBeenCalledTimes(2);
		consoleError.mockRestore();
	});
});

describe('library scan mutations', () => {
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
