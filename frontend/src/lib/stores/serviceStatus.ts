import { writable } from 'svelte/store';

interface ServiceDegradation {
	[source: string]: string;
}

const CLEAR_DELAY_MS = 10_000;

function createServiceStatusStore() {
	const { subscribe, set, update } = writable<ServiceDegradation>({});
	let clearTimer: ReturnType<typeof setTimeout> | null = null;

	function scheduleClear() {
		if (clearTimer !== null) clearTimeout(clearTimer);
		clearTimer = setTimeout(() => set({}), CLEAR_DELAY_MS);
	}

	return {
		subscribe,

		/**
		 * Merge degradation info from a backend response.
		 * Called by pageFetch / API wrappers after every successful response.
		 */
		recordFromResponse(serviceStatus: ServiceDegradation | null | undefined) {
			if (!serviceStatus || Object.keys(serviceStatus).length === 0) return;
			update((current) => ({ ...current, ...serviceStatus }));
			scheduleClear();
		},

		/**
		 * Parse the X-Degraded-Services header (comma-separated source names).
		 */
		recordFromHeader(header: string | null) {
			if (!header) return;
			const sources = header
				.split(',')
				.map((s) => s.trim())
				.filter(Boolean);
			if (sources.length === 0) return;
			const patch: ServiceDegradation = {};
			for (const src of sources) {
				patch[src] = 'error';
			}
			update((current) => ({ ...current, ...patch }));
			scheduleClear();
		},

		/** Dismiss all degradation signals (user action or navigation). */
		clear() {
			if (clearTimer !== null) clearTimeout(clearTimer);
			set({});
		}
	};
}

export const serviceStatusStore = createServiceStatusStore();
