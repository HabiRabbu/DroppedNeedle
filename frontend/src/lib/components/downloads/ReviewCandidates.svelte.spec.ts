import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { DownloadTask } from '$lib/types';

const h = vi.hoisted(() => ({
	candidates: [] as unknown[],
	pick: vi.fn(),
	cancel: vi.fn(),
	dismiss: vi.fn()
}));

vi.mock('$lib/queries/downloads/SearchQueries.svelte', () => ({
	getSearchJobQuery: () => ({
		get data() {
			return { candidates: h.candidates };
		},
		isLoading: false
	}),
	pickSearchCandidate: () => ({ mutate: h.pick, isPending: false }),
	dismissReview: () => ({ mutate: h.dismiss, isPending: false })
}));

vi.mock('$lib/queries/downloads/DownloadMutations.svelte', () => ({
	cancelDownload: () => ({ mutate: h.cancel, isPending: false })
}));

import ReviewCandidates from './ReviewCandidates.svelte';

function renderReview(task: DownloadTask) {
	return render(ReviewCandidates, { props: { task } } as unknown as Parameters<
		typeof render<typeof ReviewCandidates>
	>[1]);
}

function makeTask(): DownloadTask {
	return {
		id: 'task-1',
		search_job_id: 'job-1',
		download_type: 'album',
		album_title: 'the arrival',
		artist_name: 'Yan Qing',
		status: 'queued'
	} as unknown as DownloadTask;
}

function candidate(
	username = 'peer-a',
	tier = 'manual',
	finalScore = 0.6,
	candidateIndex: number | null = null
) {
	return {
		source: 'soulseek',
		username,
		parent_directory: 'dir',
		files: [],
		final_score: finalScore,
		tier,
		candidate_index: candidateIndex
	};
}

describe('ReviewCandidates.svelte', () => {
	beforeEach(() => {
		h.candidates = [candidate()];
		h.pick = vi.fn();
		h.cancel = vi.fn();
		h.dismiss = vi.fn();
	});

	it('offers "None of these - keep watching" next to Cancel', async () => {
		renderReview(makeTask());
		await expect.element(page.getByText('None of these - keep watching')).toBeVisible();
		await expect.element(page.getByText('Cancel request')).toBeVisible();
	});

	it('explains the safe-pick flow (verification + held listen)', async () => {
		renderReview(makeTask());
		await expect.element(page.getByText(/Picking is safe/)).toBeVisible();
	});

	it('keeps rejected results out of the default shortlist', async () => {
		h.candidates = [candidate('recommended'), candidate('weak-match', 'rejected', 0.49)];
		renderReview(makeTask());

		await expect.element(page.getByText('recommended')).toBeVisible();
		await expect.element(page.getByText('weak-match')).not.toBeInTheDocument();

		await page.getByText('Show all 2 candidates').click();
		await expect.element(page.getByText('weak-match')).toBeVisible();
	});

	it('picks the preserved index after an older review is reranked', async () => {
		h.candidates = [candidate('best-current-match', 'manual', 0.68, 7)];
		renderReview(makeTask());

		await page.getByRole('button', { name: 'Pick candidate from best-current-match' }).click();

		expect(h.pick).toHaveBeenCalledOnce();
		expect(h.pick.mock.calls[0][0]).toEqual({ jobId: 'job-1', candidate_index: 7 });
	});

	it('dismissing rejects the whole review into the watchlist', async () => {
		renderReview(makeTask());
		await page.getByText('None of these - keep watching').click();
		expect(h.dismiss).toHaveBeenCalledOnce();
		expect(h.dismiss.mock.calls[0][0]).toBe('job-1');
	});

	it('locks to "On the watchlist" after a successful dismiss', async () => {
		h.dismiss = vi.fn((_jobId: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
		renderReview(makeTask());
		await page.getByText('None of these - keep watching').click();
		await expect.element(page.getByText('On the watchlist')).toBeVisible();
		await expect.element(page.getByText('Cancel request')).toBeDisabled();
	});
});
