import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import type { FreeMusicTask } from '$lib/queries/free-music/types';

const cancelMutate = vi.fn();
const retryMutate = vi.fn();

let tasks: FreeMusicTask[] = [];

vi.mock('$lib/queries/free-music/FreeMusicQueries.svelte', () => ({
	getFreeMusicTasksQuery: () => ({
		get data() {
			return { tasks };
		}
	})
}));

vi.mock('$lib/queries/free-music/FreeMusicMutations.svelte', () => ({
	cancelFreeMusicMutation: () => ({ mutate: cancelMutate, isPending: false }),
	retryFreeMusicMutation: () => ({ mutate: retryMutate, isPending: false })
}));

vi.mock('$lib/stores/authStore.svelte', () => ({ authStore: { isAdmin: false } }));

import FreeMusicQueue from './FreeMusicQueue.svelte';

function task(overrides: Partial<FreeMusicTask> = {}): FreeMusicTask {
	return {
		id: 'T1',
		user_id: 'u1',
		kind: 'album',
		mbid: 'rg1',
		artist: 'Brad Sucks',
		title: "Guess Who's a Mess",
		status: 'downloading',
		created_at: 0,
		updated_at: 0,
		identifier: 'jamendo-117853',
		licence_url: 'http://creativecommons.org/licenses/by-nc-sa/3.0/',
		format: 'mp3',
		files_total: 10,
		files_completed: 4,
		bytes_total: 1000,
		bytes_downloaded: 250,
		error: null,
		...overrides
	};
}

describe('FreeMusicQueue.svelte', () => {
	beforeEach(() => {
		cancelMutate.mockClear();
		retryMutate.mockClear();
	});

	it('renders nothing when there are no tasks', async () => {
		tasks = [];
		render(FreeMusicQueue);
		await expect.element(page.getByText('Free Music')).not.toBeInTheDocument();
	});

	it('shows the licence a download is being taken under', async () => {
		tasks = [task()];
		render(FreeMusicQueue);
		await expect.element(page.getByText('CC BY-NC-SA 3.0')).toBeInTheDocument();
	});

	it('names a public-domain licence rather than showing a raw URL', async () => {
		tasks = [task({ licence_url: 'http://creativecommons.org/publicdomain/zero/1.0/' })];
		render(FreeMusicQueue);
		await expect.element(page.getByText('Public domain (ZERO)')).toBeInTheDocument();
	});

	it('shows progress and offers cancel while downloading', async () => {
		tasks = [task()];
		render(FreeMusicQueue);
		await expect.element(page.getByText(/4\/10 files/)).toBeInTheDocument();
		await page.getByRole('button', { name: /Cancel/ }).click();
		expect(cancelMutate).toHaveBeenCalledWith('T1');
	});

	it('offers retry, and surfaces the reason, when a download failed', async () => {
		tasks = [task({ status: 'failed', error: 'The download failed. Try again.' })];
		render(FreeMusicQueue);
		await expect.element(page.getByText('The download failed. Try again.')).toBeInTheDocument();
		await page.getByRole('button', { name: 'Retry' }).click();
		expect(retryMutate).toHaveBeenCalledWith('T1');
	});

	it('a completed task offers neither cancel nor retry', async () => {
		tasks = [task({ status: 'completed', files_completed: 10 })];
		render(FreeMusicQueue);
		await expect.element(page.getByText('In your library')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: /Cancel/ })).not.toBeInTheDocument();
	});
});
