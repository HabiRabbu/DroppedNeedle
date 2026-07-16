import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
	invalidate: vi.fn().mockResolvedValue(undefined)
}));

vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: h.invalidate
}));

import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import { createLibraryActivityEvents } from './LibraryActivityEvents';

class FakeEventSource {
	static instances: FakeEventSource[] = [];
	readonly url: string;
	readonly listeners = new Map<string, Set<() => void>>();
	closed = false;

	constructor(url: string | URL) {
		this.url = String(url);
		FakeEventSource.instances.push(this);
	}

	addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
		const callback = listener as () => void;
		const listeners = this.listeners.get(type) ?? new Set<() => void>();
		listeners.add(callback);
		this.listeners.set(type, listeners);
	}

	close(): void {
		this.closed = true;
	}

	emit(type: string): void {
		for (const listener of this.listeners.get(type) ?? []) listener();
	}
}

beforeEach(() => {
	vi.clearAllMocks();
	FakeEventSource.instances = [];
	vi.stubGlobal('EventSource', FakeEventSource);
});

describe('createLibraryActivityEvents', () => {
	it('re-reads durable state whenever either stream opens or reconnects', () => {
		const events = createLibraryActivityEvents();
		events.start(true);
		expect(FakeEventSource.instances).toHaveLength(2);

		FakeEventSource.instances[0].emit('open');
		expect(h.invalidate).toHaveBeenCalledWith({
			queryKey: LibraryQueryKeyFactory.activityPrefix()
		});

		h.invalidate.mockClear();
		FakeEventSource.instances[1].emit('open');
		expect(h.invalidate).toHaveBeenCalledWith({
			queryKey: LibraryQueryKeyFactory.operationsPrefix()
		});
		expect(h.invalidate).toHaveBeenCalledWith({
			queryKey: LibraryQueryKeyFactory.reviewsPrefix()
		});
		expect(h.invalidate).toHaveBeenCalledWith({
			queryKey: LibraryQueryKeyFactory.activityPrefix()
		});
	});

	it('uses SSE only as an invalidation signal and closes every replaced stream', () => {
		const events = createLibraryActivityEvents();
		events.start(true);
		const first = [...FakeEventSource.instances];
		first[1].emit('activity.changed');
		expect(h.invalidate).toHaveBeenCalledWith({
			queryKey: LibraryQueryKeyFactory.operationsPrefix()
		});

		events.start(false);
		expect(first.every((source) => source.closed)).toBe(true);
		expect(FakeEventSource.instances).toHaveLength(3);
		events.stop();
		expect(FakeEventSource.instances[2].closed).toBe(true);
	});
});
