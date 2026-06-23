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

// Entries scoped per user so a shared browser never serves one user's queue to
// another. The change event still carries only `source` (what consumers react to).
function scopedSuffix(userId: string, source?: string): string {
	return source ? `${userId}:${source}` : userId;
}

function notifyQueueCacheChanged(source?: string): void {
	if (typeof window === 'undefined') return;
	window.dispatchEvent(
		new CustomEvent<{ source?: string }>(QUEUE_CACHE_EVENT, {
			detail: { source }
		})
	);
}

export function subscribeQueueCacheChanges(listener: (source?: string) => void): () => void {
	if (typeof window === 'undefined') return () => {};

	const handler = (event: Event) => {
		const customEvent = event as CustomEvent<{ source?: string }>;
		listener(customEvent.detail?.source);
	};

	window.addEventListener(QUEUE_CACHE_EVENT, handler);
	return () => {
		window.removeEventListener(QUEUE_CACHE_EVENT, handler);
	};
}

export const getQueueCachedData = (userId: string, source?: string) => {
	const suffix = scopedSuffix(userId, source);
	const cached = queueCache.get(suffix);
	if (!cached) return null;

	if (queueCache.isStale(cached.timestamp)) {
		queueCache.remove(suffix);
		notifyQueueCacheChanged(source);
		return null;
	}

	return cached;
};

export const setQueueCachedData = (data: QueueCacheData, userId: string, source?: string) => {
	queueCache.set(data, scopedSuffix(userId, source));
	notifyQueueCacheChanged(source);
};

export const removeQueueCachedData = (userId: string, source?: string) => {
	queueCache.remove(scopedSuffix(userId, source));
	notifyQueueCacheChanged(source);
};
export const updateDiscoverQueueCacheTTL = queueCache.updateTTL;

export function removeAllQueueCachedData(): void {
	clearLocalStorageNamespace(CACHE_KEYS.DISCOVER_QUEUE);
	notifyQueueCacheChanged();
}
