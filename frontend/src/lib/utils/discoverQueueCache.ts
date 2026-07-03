import { CACHE_KEYS, CACHE_TTL } from '$lib/constants';
import { clearLocalStorageNamespace, createLocalStorageCache } from '$lib/utils/localStorageCache';
import type { DiscoverQueueItemFull } from '$lib/types';

export interface QueueCacheData {
	items: DiscoverQueueItemFull[];
	currentIndex: number;
	queueId: string;
}

const queueCache = createLocalStorageCache<QueueCacheData>(
	CACHE_KEYS.DISCOVER_QUEUE,
	CACHE_TTL.DISCOVER_QUEUE
);

const QUEUE_CACHE_EVENT = 'discover-queue-cache-changed';

function notifyQueueCacheChanged(): void {
	if (typeof window === 'undefined') return;
	window.dispatchEvent(new CustomEvent(QUEUE_CACHE_EVENT));
}

export function subscribeQueueCacheChanges(listener: () => void): () => void {
	if (typeof window === 'undefined') return () => {};

	const handler = () => listener();
	window.addEventListener(QUEUE_CACHE_EVENT, handler);
	return () => {
		window.removeEventListener(QUEUE_CACHE_EVENT, handler);
	};
}

// Entries scoped per user so a shared browser never serves one user's queue to
// another. One queue per user (the source dimension is gone: the queue follows
// the user's primary source server-side).
export const getQueueCachedData = (userId: string) => {
	const cached = queueCache.get(userId);
	if (!cached) return null;

	if (queueCache.isStale(cached.timestamp)) {
		queueCache.remove(userId);
		notifyQueueCacheChanged();
		return null;
	}

	return cached;
};

export const setQueueCachedData = (data: QueueCacheData, userId: string) => {
	queueCache.set(data, userId);
	notifyQueueCacheChanged();
};

export const removeQueueCachedData = (userId: string) => {
	queueCache.remove(userId);
	notifyQueueCacheChanged();
};
export const updateDiscoverQueueCacheTTL = queueCache.updateTTL;

export function removeAllQueueCachedData(): void {
	clearLocalStorageNamespace(CACHE_KEYS.DISCOVER_QUEUE);
	notifyQueueCacheChanged();
}
