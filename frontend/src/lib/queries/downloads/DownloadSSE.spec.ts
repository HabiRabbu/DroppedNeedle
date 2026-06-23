import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

const { createDownloadStream } = await import('./DownloadSSE.svelte');

describe('createDownloadStream', () => {
	it('maps progress events to rune state', () => {
		const s = createDownloadStream();
		s.start('t1');
		FakeEventSource.instances[0].emit('progress', {
			bytes_downloaded: 5,
			bytes_total: 10,
			files_completed: 1,
			files_total: 2,
			progress_percent: 50
		});
		expect(s.state.progress?.progress_percent).toBe(50);
		expect(s.state.progress?.bytes_total).toBe(10);
	});

	it('captures status events', () => {
		const s = createDownloadStream();
		s.start('t1');
		FakeEventSource.instances[0].emit('status', { status: 'downloading' });
		expect(s.state.status).toBe('downloading');
	});

	it('marks done and closes the stream on the complete event', () => {
		const s = createDownloadStream();
		s.start('t1');
		const es = FakeEventSource.instances[0];
		es.emit('complete', { status: 'completed' });
		expect(s.state.done).toBe(true);
		expect(s.state.status).toBe('completed');
		expect(es.closed).toBe(true);
	});

	it('stop() closes the underlying EventSource', () => {
		const s = createDownloadStream();
		s.start('t1');
		const es = FakeEventSource.instances[0];
		s.stop();
		expect(es.closed).toBe(true);
	});
});
