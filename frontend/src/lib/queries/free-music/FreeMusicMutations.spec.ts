import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@tanstack/svelte-query', () => ({
	createMutation: vi.fn((factory: () => Record<string, unknown>) => factory())
}));

vi.mock('$lib/api/client', () => ({
	api: { global: { delete: vi.fn() } }
}));

vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn().mockResolvedValue(undefined)
}));

vi.mock('$lib/stores/toast', () => ({
	toastStore: { show: vi.fn() }
}));

import { api } from '$lib/api/client';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';
import {
	clearFreeMusicHistoryMutation,
	removeFreeMusicHistoryMutation
} from './FreeMusicMutations.svelte';

const mockDelete = vi.mocked(api.global.delete);

beforeEach(() => {
	vi.clearAllMocks();
	mockDelete.mockResolvedValue({ cleared: 1 });
});

describe('Free Music history mutations', () => {
	it('removes one task and refreshes the persisted queue', async () => {
		const mutation = removeFreeMusicHistoryMutation() as unknown as {
			mutationFn: (taskId: string) => Promise<{ cleared: number }>;
			onSuccess: () => Promise<void>;
		};

		await mutation.mutationFn('task-1');
		await mutation.onSuccess();

		expect(mockDelete).toHaveBeenCalledWith('/api/v1/free-music/tasks/task-1');
		expect(invalidateQueriesWithPersister).toHaveBeenCalledWith({
			queryKey: ['free-music']
		});
		expect(toastStore.show).toHaveBeenCalledWith({
			message: 'Removed from Free Music history.',
			type: 'info'
		});
	});

	it('clears the admin view and reports the number removed', async () => {
		const mutation = clearFreeMusicHistoryMutation() as unknown as {
			mutationFn: (all: boolean) => Promise<{ cleared: number }>;
			onSuccess: (data: { cleared: number }) => Promise<void>;
		};

		await mutation.mutationFn(true);
		await mutation.onSuccess({ cleared: 3 });

		expect(mockDelete).toHaveBeenCalledWith('/api/v1/free-music/tasks?all=true');
		expect(toastStore.show).toHaveBeenCalledWith({
			message: 'Removed 3 items from Free Music history.',
			type: 'info'
		});
	});
});
