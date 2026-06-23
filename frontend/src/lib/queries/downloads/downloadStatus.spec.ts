import { describe, expect, it } from 'vitest';

import type { DownloadTask } from '$lib/types';

import {
	activeCount,
	bucketDownloads,
	canCancel,
	canRetry,
	derivedDownloadStatus,
	nowPressing,
	tabForTask
} from './downloadStatus';

function task(overrides: Partial<DownloadTask> = {}): DownloadTask {
	return {
		id: 't',
		user_id: 'u',
		download_type: 'album',
		release_group_mbid: 'rg',
		recording_mbid: null,
		artist_name: 'A',
		album_title: 'B',
		track_title: null,
		year: 2020,
		status: 'queued',
		progress_percent: 0,
		total_size_bytes: null,
		downloaded_bytes: 0,
		files_total: 0,
		files_completed: 0,
		files_failed: 0,
		source_username: null,
		search_job_id: null,
		candidate_index: null,
		preflight_score: null,
		final_path: null,
		error_message: null,
		retry_count: 0,
		created_at: 0,
		updated_at: 0,
		...overrides
	};
}

describe('derivedDownloadStatus', () => {
	it('queued with no search job is "searching"', () => {
		expect(derivedDownloadStatus(task({ status: 'queued', search_job_id: null }))).toBe(
			'searching'
		);
	});

	it('queued with a search job but no picked candidate is "awaiting_review"', () => {
		expect(
			derivedDownloadStatus(task({ status: 'queued', search_job_id: 'j', candidate_index: null }))
		).toBe('awaiting_review');
	});

	it('queued with a picked candidate stays "queued" (transient)', () => {
		expect(
			derivedDownloadStatus(task({ status: 'queued', search_job_id: 'j', candidate_index: 0 }))
		).toBe('queued');
	});

	it('passes non-queued statuses through unchanged', () => {
		expect(derivedDownloadStatus(task({ status: 'downloading' }))).toBe('downloading');
		expect(derivedDownloadStatus(task({ status: 'completed' }))).toBe('completed');
	});
});

describe('tabForTask + bucketDownloads + counts', () => {
	it('routes derived states to the right tab', () => {
		expect(tabForTask(task({ status: 'queued' }))).toBe('active'); // searching
		expect(tabForTask(task({ status: 'downloading' }))).toBe('active');
		expect(tabForTask(task({ status: 'processing' }))).toBe('active');
		expect(tabForTask(task({ status: 'queued', search_job_id: 'j', candidate_index: null }))).toBe(
			'review'
		);
		expect(tabForTask(task({ status: 'completed' }))).toBe('completed');
		expect(tabForTask(task({ status: 'partial' }))).toBe('completed');
		expect(tabForTask(task({ status: 'failed' }))).toBe('failed');
		expect(tabForTask(task({ status: 'cancelled' }))).toBe('failed');
	});

	it('buckets and sorts most-recent first', () => {
		const a = task({ id: 'a', status: 'downloading', created_at: 1 });
		const b = task({ id: 'b', status: 'downloading', created_at: 2 });
		expect(bucketDownloads([a, b]).active.map((t) => t.id)).toEqual(['b', 'a']);
	});

	it('counts only active tasks', () => {
		expect(
			activeCount([
				task({ status: 'downloading' }),
				task({ status: 'completed' }),
				task({ status: 'queued' })
			])
		).toBe(2);
	});
});

describe('canCancel / canRetry', () => {
	it('allows cancel while searching/queued/downloading but not processing', () => {
		expect(canCancel(task({ status: 'queued' }))).toBe(true); // searching
		expect(canCancel(task({ status: 'queued', search_job_id: 'j', candidate_index: 0 }))).toBe(
			true
		);
		expect(canCancel(task({ status: 'downloading' }))).toBe(true);
		expect(canCancel(task({ status: 'processing' }))).toBe(false);
		expect(canCancel(task({ status: 'completed' }))).toBe(false);
	});

	it('allows retry only for failed/cancelled/partial', () => {
		expect(canRetry(task({ status: 'failed' }))).toBe(true);
		expect(canRetry(task({ status: 'cancelled' }))).toBe(true);
		expect(canRetry(task({ status: 'partial' }))).toBe(true);
		expect(canRetry(task({ status: 'downloading' }))).toBe(false);
	});
});

describe('nowPressing', () => {
	it('prefers the most recent downloading/processing task over a newer searching one', () => {
		const dl = task({ id: 'dl', status: 'downloading', created_at: 1 });
		const searching = task({ id: 's', status: 'queued', created_at: 5 });
		expect(nowPressing([dl, searching])?.id).toBe('dl');
	});

	it('falls back to the most recent active task when none are live', () => {
		const s1 = task({ id: 's1', status: 'queued', created_at: 1 });
		const s2 = task({ id: 's2', status: 'queued', created_at: 2 });
		expect(nowPressing([s1, s2])?.id).toBe('s2');
	});

	it('returns null when nothing is active', () => {
		expect(nowPressing([task({ status: 'completed' })])).toBeNull();
	});
});
