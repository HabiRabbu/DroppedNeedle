import { createMutation } from '@tanstack/svelte-query';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';

import { FreeMusicQueryKeyFactory } from './FreeMusicQueryKeyFactory';
import type { FreeMusicTask } from './types';

const invalidateTasks = () =>
	invalidateQueriesWithPersister({ queryKey: FreeMusicQueryKeyFactory.prefix });

export const cancelFreeMusicMutation = () =>
	createMutation(() => ({
		mutationFn: (taskId: string) => api.global.post<FreeMusicTask>(API.freeMusic.cancel(taskId)),
		onSuccess: async () => {
			toastStore.show({ message: 'Download cancelled.', type: 'info' });
			await invalidateTasks();
		},
		onError: (error: Error) => {
			toastStore.show({ message: error.message || 'Cancelling failed.', type: 'error' });
		}
	}));

export const retryFreeMusicMutation = () =>
	createMutation(() => ({
		mutationFn: (taskId: string) => api.global.post<FreeMusicTask>(API.freeMusic.retry(taskId)),
		onSuccess: async () => {
			toastStore.show({ message: 'Trying again.', type: 'success' });
			await invalidateTasks();
		},
		onError: (error: Error) => {
			toastStore.show({ message: error.message || 'Retrying failed.', type: 'error' });
		}
	}));
