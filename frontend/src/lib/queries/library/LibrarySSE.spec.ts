import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

class FakeEventSource {
	static instances: FakeEventSource[] = [];
	url: string;
	listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
	closed = false;

	constructor(url: string) {
		this.url = url;
		FakeEventSource.instances.push(this);
	}

	addEventListener(type: string, cb: (e: MessageEvent) => void) {
		(this.listeners[type] ??= []).push(cb);
	}

	close() {
		this.closed = true;
	}

	emit(type: string, data: unknown) {
		const ev = { data: JSON.stringify(data) } as MessageEvent;
		for (const cb of this.listeners[type] ?? []) cb(ev);
	}
}

beforeEach(() => {
	FakeEventSource.instances = [];
	vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

const { createLibraryScanStream } = await import('./LibrarySSE.svelte');

describe('createLibraryScanStream', () => {
	it('maps started + progress events to rune state', () => {
		const scan = createLibraryScanStream();
		scan.start();
		const es = FakeEventSource.instances[0];
		es.emit('started', { total: 10 });
		es.emit('progress', { processed: 4, total: 10, matched: 3, unmatched: 1 });
		expect(scan.state.status).toBe('scanning');
		expect(scan.state.processed).toBe(4);
		expect(scan.state.total).toBe(10);
		expect(scan.state.matched).toBe(3);
		expect(scan.state.unmatched).toBe(1);
	});

	it('transitions to complete and closes the stream on the complete event', () => {
		const scan = createLibraryScanStream();
		scan.start();
		const es = FakeEventSource.instances[0];
		es.emit('complete', { stats: { matched: 9, unmatched: 1 } });
		expect(scan.state.status).toBe('complete');
		expect(scan.state.matched).toBe(9);
		expect(es.closed).toBe(true);
	});

	it('enters the finalising phase and clears it on complete', () => {
		const scan = createLibraryScanStream();
		scan.start();
		const es = FakeEventSource.instances[0];
		es.emit('finalizing', { phase: 'artists', remaining: 12, total: 40 });
		expect(scan.state.status).toBe('scanning');
		expect(scan.state.finalizing).toEqual({ remaining: 12, total: 40 });
		es.emit('complete', { stats: { matched: 9, unmatched: 1 } });
		expect(scan.state.finalizing).toBeNull();
	});

	it('captures a non-fatal warning from the complete event', () => {
		const scan = createLibraryScanStream();
		scan.start();
		FakeEventSource.instances[0].emit('complete', {
			stats: { matched: 9, unmatched: 1 },
			warning: 'MusicBrainz was unreachable'
		});
		expect(scan.state.status).toBe('complete');
		expect(scan.state.warning).toBe('MusicBrainz was unreachable');
	});

	it('leaves warning null when the complete event has none', () => {
		const scan = createLibraryScanStream();
		scan.start();
		FakeEventSource.instances[0].emit('complete', { stats: { matched: 9, unmatched: 1 } });
		expect(scan.state.warning).toBeNull();
	});

	it('marks failed with the error message on a failed event', () => {
		const scan = createLibraryScanStream();
		scan.start();
		FakeEventSource.instances[0].emit('failed', { error: 'boom' });
		expect(scan.state.status).toBe('failed');
		expect(scan.state.errorMessage).toBe('boom');
	});

	it('stop() closes the underlying EventSource', () => {
		const scan = createLibraryScanStream();
		scan.start();
		const es = FakeEventSource.instances[0];
		scan.stop();
		expect(es.closed).toBe(true);
	});
});
