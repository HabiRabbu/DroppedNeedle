import { API } from '$lib/constants';
import type { ScanStatus } from '$lib/types';

export interface LibraryScanState {
	status: ScanStatus;
	processed: number;
	total: number;
	matched: number;
	unmatched: number;
	errorMessage: string | null;
	/** Non-fatal note on an otherwise-complete scan. */
	warning: string | null;
	/** Set while finalising past 100% (resolving album artists). */
	finalizing: { remaining: number; total: number } | null;
}

/**
 * Live scan progress via native `EventSource`. The backend emits the events
 * `started` / `progress` / `complete` / `cancelled` / `failed` on the
 * `library:scan` channel (see `library_scanner.py`). `EventSource` can't send
 * custom headers, but the `droppedneedle_session` cookie authenticates it
 * automatically; bearer-token clients fall back to the polling status query.
 */
export function createLibraryScanStream() {
	let state = $state<LibraryScanState>({
		status: 'idle',
		processed: 0,
		total: 0,
		matched: 0,
		unmatched: 0,
		errorMessage: null,
		warning: null,
		finalizing: null
	});

	let source: EventSource | null = null;

	function parse(e: Event): Record<string, unknown> {
		try {
			return JSON.parse((e as MessageEvent).data) as Record<string, unknown>;
		} catch {
			return {};
		}
	}

	function start() {
		if (source) return;
		state = { ...state, status: 'scanning', errorMessage: null };
		source = new EventSource(API.library.scanStream());

		source.addEventListener('started', (e) => {
			const d = parse(e);
			state = { ...state, status: 'scanning', total: Number(d.total ?? state.total) };
		});
		source.addEventListener('progress', (e) => {
			const d = parse(e);
			state = {
				...state,
				status: 'scanning',
				processed: Number(d.processed ?? state.processed),
				total: Number(d.total ?? state.total),
				matched: Number(d.matched ?? state.matched),
				unmatched: Number(d.unmatched ?? state.unmatched)
			};
		});
		source.addEventListener('finalizing', (e) => {
			const d = parse(e);
			state = {
				...state,
				status: 'scanning',
				finalizing: { remaining: Number(d.remaining ?? 0), total: Number(d.total ?? 0) }
			};
		});
		source.addEventListener('complete', (e) => {
			const d = parse(e);
			const stats = (d.stats ?? {}) as Record<string, number>;
			state = {
				...state,
				status: 'complete',
				matched: Number(stats.matched ?? state.matched),
				unmatched: Number(stats.unmatched ?? state.unmatched),
				warning: typeof d.warning === 'string' ? d.warning : null,
				finalizing: null
			};
			stop();
		});
		source.addEventListener('cancelled', () => {
			state = { ...state, status: 'cancelled', finalizing: null };
			stop();
		});
		source.addEventListener('failed', (e) => {
			const d = parse(e);
			state = {
				...state,
				status: 'failed',
				errorMessage: String(d.error ?? 'Scan failed'),
				finalizing: null
			};
			stop();
		});
		// On disconnect the browser auto-reconnects; surface a soft note while it
		// retries. Consumers can also rely on the polling scanStatus query (UX-19).
		source.addEventListener('error', () => {
			if (state.status === 'scanning') {
				state = { ...state, errorMessage: 'Reconnecting…' };
			}
		});
	}

	function stop() {
		if (source) {
			source.close();
			source = null;
		}
	}

	function reset() {
		state = {
			status: 'idle',
			processed: 0,
			total: 0,
			matched: 0,
			unmatched: 0,
			errorMessage: null,
			warning: null,
			finalizing: null
		};
	}

	return {
		get state() {
			return state;
		},
		start,
		stop,
		reset
	};
}
