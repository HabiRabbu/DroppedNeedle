import { browser } from '$app/environment';
import { api } from '$lib/api/client';

const POLL_INTERVAL_MS = 15_000;

function createPendingApprovalCountStore() {
	let count = $state(0);
	let pollInterval: ReturnType<typeof setInterval> | null = null;

	async function poll(): Promise<void> {
		try {
			const data = await api.global.get<{ count?: number }>(
				'/api/v1/requests/pending-approvals/count'
			);
			count = data.count ?? 0;
		} catch {
			// ignore polling errors (e.g. non-admin users get 403)
		}
	}

	function stopPolling(): void {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	function startPolling(): void {
		if (!browser) return;
		void poll();
		stopPolling();
		pollInterval = setInterval(() => void poll(), POLL_INTERVAL_MS);
	}

	function notify(newCount?: number): void {
		if (typeof newCount === 'number') {
			count = newCount;
			return;
		}
		void poll();
	}

	return {
		get count() {
			return count;
		},
		startPolling,
		stopPolling,
		notify
	};
}

export const pendingApprovalCountStore = createPendingApprovalCountStore();
