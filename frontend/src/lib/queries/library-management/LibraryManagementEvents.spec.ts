import { beforeEach, describe, expect, it, vi } from 'vitest';

const invalidate = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock('./LibraryManagementInvalidation', () => ({
	invalidateLibraryManagementSurfaces: invalidate
}));

import {
	createLibraryManagementEvents,
	parseLibraryManagementActivityEvent
} from './LibraryManagementEvents';

class FakeEventSource {
	static instances: FakeEventSource[] = [];
	readonly url: string;
	readonly listeners = new Map<string, Set<EventListener>>();
	closed = false;

	constructor(url: string | URL) {
		this.url = String(url);
		FakeEventSource.instances.push(this);
	}

	addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
		const callback = listener as EventListener;
		const listeners = this.listeners.get(type) ?? new Set<EventListener>();
		listeners.add(callback);
		this.listeners.set(type, listeners);
	}

	close(): void {
		this.closed = true;
	}

	emit(type: string, data = '', lastEventId = ''): void {
		const event = type === 'open' ? new Event(type) : new MessageEvent(type, { data, lastEventId });
		for (const listener of this.listeners.get(type) ?? []) listener(event);
	}
}

beforeEach(() => {
	vi.clearAllMocks();
	FakeEventSource.instances = [];
	vi.stubGlobal('EventSource', FakeEventSource);
});

describe('parseLibraryManagementActivityEvent', () => {
	it('accepts the durable revision payload and rejects malformed revisions', () => {
		expect(
			parseLibraryManagementActivityEvent(
				'{"id":"activity:4","revisions":{"operation":4,"scan":2}}'
			)
		).toEqual({ id: 'activity:4', revisions: { operation: 4, scan: 2 } });
		expect(parseLibraryManagementActivityEvent('{"id":"activity:4","revisions":[]}')).toBeNull();
		expect(
			parseLibraryManagementActivityEvent('{"id":"activity:4","revisions":{"operation":"four"}}')
		).toBeNull();
		expect(parseLibraryManagementActivityEvent('not-json')).toBeNull();
	});
});

describe('createLibraryManagementEvents', () => {
	it('re-reads durable state on open and de-duplicates replayed event IDs', () => {
		const events = createLibraryManagementEvents();
		events.start();
		const first = FakeEventSource.instances[0];
		expect(first.url).toBe('/api/v1/library/operations/stream');

		first.emit('open');
		expect(invalidate).toHaveBeenCalledOnce();
		invalidate.mockClear();
		const payload = '{"id":"activity:7","revisions":{"operation":7}}';
		first.emit('activity.changed', payload, 'activity:7');
		first.emit('activity.changed', payload, 'activity:7');
		expect(invalidate).toHaveBeenCalledOnce();

		events.start();
		expect(first.closed).toBe(true);
		const reconnected = FakeEventSource.instances[1];
		reconnected.emit('open');
		expect(invalidate).toHaveBeenCalledTimes(2);
		invalidate.mockClear();
		reconnected.emit('activity.changed', payload, 'activity:7');
		expect(invalidate).not.toHaveBeenCalled();
		reconnected.emit(
			'activity.changed',
			'{"id":"activity:8","revisions":{"operation":8}}',
			'activity:8'
		);
		expect(invalidate).toHaveBeenCalledOnce();

		events.stop();
		expect(reconnected.closed).toBe(true);
	});

	it('invalidates distinct revision vectors even when their maximum is unchanged', () => {
		const events = createLibraryManagementEvents();
		events.start();
		const source = FakeEventSource.instances[0];
		source.emit(
			'activity.changed',
			'{"id":"activity:first","revisions":{"scan":100,"operation":5}}',
			'activity:first'
		);
		source.emit(
			'activity.changed',
			'{"id":"activity:second","revisions":{"scan":100,"operation":6}}',
			'activity:second'
		);

		expect(invalidate).toHaveBeenCalledTimes(2);
	});

	it('ignores malformed stream payloads', () => {
		const events = createLibraryManagementEvents();
		events.start();
		FakeEventSource.instances[0].emit('activity.changed', '{"id":"bad"}');
		expect(invalidate).not.toHaveBeenCalled();
	});
});
