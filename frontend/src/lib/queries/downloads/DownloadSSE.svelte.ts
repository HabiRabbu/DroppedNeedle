import { API } from '$lib/constants';
import type { DownloadProgress } from '$lib/types';

interface DownloadStreamState {
	progress: DownloadProgress | null;
	status: string | null;
	done: boolean;
}

function parse(event: Event): Record<string, unknown> {
	try {
		return JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
	} catch {
		return {};
	}
}

// EventSource authenticates via the droppedneedle_session cookie (no custom headers).
// no 'error' handler so keepalive gaps/close don't clobber a terminal state
export function createDownloadStream() {
	let state = $state<DownloadStreamState>({ progress: null, status: null, done: false });
	let source: EventSource | null = null;

	function stop() {
		if (source) {
			source.close();
			source = null;
		}
	}

	function start(taskId: string) {
		stop();
		state = { progress: null, status: null, done: false };
		source = new EventSource(API.downloads.stream(taskId));
		source.addEventListener('status', (e) => {
			const d = parse(e);
			state = { ...state, status: (d.status as string) ?? state.status };
		});
		source.addEventListener('progress', (e) => {
			const d = parse(e);
			state = {
				...state,
				progress: {
					bytes_downloaded: Number(d.bytes_downloaded ?? 0),
					bytes_total: Number(d.bytes_total ?? 0),
					files_completed: Number(d.files_completed ?? 0),
					files_total: Number(d.files_total ?? 0),
					progress_percent: Number(d.progress_percent ?? 0)
				}
			};
		});
		source.addEventListener('complete', (e) => {
			const d = parse(e);
			state = { ...state, status: (d.status as string) ?? state.status, done: true };
			stop();
		});
	}

	return {
		get state() {
			return state;
		},
		start,
		stop
	};
}
