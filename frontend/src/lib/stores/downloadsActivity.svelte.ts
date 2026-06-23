import { browser } from '$app/environment';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { activeCount } from '$lib/queries/downloads/downloadStatus';
import type { DownloadListResponse } from '$lib/types';

// nav-badge active-downloads count; light 10s poll so background downloads show
// anywhere (the /downloads page polls faster). best-effort, transient errors ignored
let count = $state(0);
let timer: ReturnType<typeof setInterval> | null = null;
let started = false;

async function poll(): Promise<void> {
	try {
		const res = await api.global.get<DownloadListResponse>(API.downloads.list(undefined, 1, 100));
		count = activeCount(res.items);
	} catch {
		// non-critical; leave the last known count in place
	}
}

export const downloadsActivity = {
	get count() {
		return count;
	},
	get isActive() {
		return count > 0;
	},
	start(): void {
		if (!browser || started) return;
		started = true;
		void poll();
		timer = setInterval(() => void poll(), 10000);
	},
	refresh(): void {
		void poll();
	},
	stop(): void {
		if (timer) clearInterval(timer);
		timer = null;
		started = false;
		count = 0;
	}
};
