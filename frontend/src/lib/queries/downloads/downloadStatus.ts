// lucide-free so the lucide-free nav store can import it. "searching"/"awaiting_review" are derived (backend exposes no search_jobs.status):
//   queued + no search_job_id             -> searching
//   queued + search_job_id + no candidate -> awaiting_review (parked manual tier)
//   otherwise                             -> raw status
import type { DownloadStatus, DownloadTask } from '$lib/types';

export type DerivedDownloadStatus = 'searching' | 'awaiting_review' | DownloadStatus;
export type DownloadTab = 'active' | 'review' | 'completed' | 'failed' | 'quarantine';

export function derivedDownloadStatus(task: DownloadTask): DerivedDownloadStatus {
	if (task.status === 'queued') {
		if (!task.search_job_id) return 'searching';
		if (task.candidate_index === null || task.candidate_index === undefined) {
			return 'awaiting_review';
		}
	}
	return task.status;
}

// mirrors the backend _ACTIVE_STATUSES - a task still in flight (not a terminal state)
const ACTIVE_STATUSES: DownloadStatus[] = ['queued', 'downloading', 'processing'];

export function isActiveDownloadStatus(status: DownloadStatus): boolean {
	return ACTIVE_STATUSES.includes(status);
}

export function hasActiveTask(tasks: DownloadTask[]): boolean {
	return tasks.some((t) => isActiveDownloadStatus(t.status));
}

export type DownloadBucketTab = Exclude<DownloadTab, 'quarantine'>;

export function tabForTask(task: DownloadTask): DownloadBucketTab {
	const derived = derivedDownloadStatus(task);
	if (derived === 'awaiting_review') return 'review';
	if (derived === 'completed' || derived === 'partial') return 'completed';
	if (derived === 'failed' || derived === 'cancelled') return 'failed';
	return 'active';
}

export type DownloadBuckets = Record<DownloadBucketTab, DownloadTask[]>;

export function bucketDownloads(tasks: DownloadTask[]): DownloadBuckets {
	const buckets: DownloadBuckets = { active: [], review: [], completed: [], failed: [] };
	for (const task of tasks) buckets[tabForTask(task)].push(task);
	for (const key of Object.keys(buckets) as DownloadBucketTab[]) {
		buckets[key].sort((a, b) => b.created_at - a.created_at);
	}
	return buckets;
}

export function activeCount(tasks: DownloadTask[]): number {
	let count = 0;
	for (const task of tasks) if (tabForTask(task) === 'active') count++;
	return count;
}

// no cancel during processing: file move is unsafe to interrupt (UX-8)
export function canCancel(task: DownloadTask): boolean {
	const derived = derivedDownloadStatus(task);
	return derived === 'searching' || derived === 'queued' || derived === 'downloading';
}

export function canRetry(task: DownloadTask): boolean {
	return task.status === 'failed' || task.status === 'cancelled' || task.status === 'partial';
}

// featured "now pressing": most recent downloading/processing item, else most recent active item
export function nowPressing(tasks: DownloadTask[]): DownloadTask | null {
	const active = tasks.filter((t) => tabForTask(t) === 'active');
	if (active.length === 0) return null;
	const live = active.filter((t) => t.status === 'downloading' || t.status === 'processing');
	const pool = live.length > 0 ? live : active;
	return pool.reduce((best, t) => (t.created_at > best.created_at ? t : best), pool[0]);
}
