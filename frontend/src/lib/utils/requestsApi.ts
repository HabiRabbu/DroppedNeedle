import type { ActiveRequestsResponse, RequestHistoryResponse } from '$lib/types';
import { api } from '$lib/api/client';
import { requestCountStore } from '$lib/stores/requestCountStore.svelte';
export type { ActiveRequestsResponse, RequestHistoryResponse } from '$lib/types';

export function notifyRequestCountChanged(count?: number): void {
	requestCountStore.notify(count);
}

export async function fetchActiveRequests(signal?: AbortSignal): Promise<ActiveRequestsResponse> {
	return api.global.get<ActiveRequestsResponse>('/api/v1/requests/active', { signal });
}

export async function fetchRequestHistory(
	page: number = 1,
	pageSize: number = 20,
	status?: string,
	signal?: AbortSignal,
	sort?: string
): Promise<RequestHistoryResponse> {
	const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
	if (status) params.set('status', status);
	if (sort) params.set('sort', sort);
	return api.global.get<RequestHistoryResponse>(`/api/v1/requests/history?${params}`, { signal });
}

export async function cancelRequest(
	musicbrainzId: string
): Promise<{ success: boolean; message: string }> {
	const data = await api.global.delete<{ success: boolean; message: string }>(
		`/api/v1/requests/active/${musicbrainzId}`
	);
	notifyRequestCountChanged();
	return data;
}

export async function retryRequest(
	musicbrainzId: string
): Promise<{ success: boolean; message: string }> {
	const data = await api.global.post<{ success: boolean; message: string }>(
		`/api/v1/requests/retry/${musicbrainzId}`
	);
	notifyRequestCountChanged();
	return data;
}

export async function clearHistoryItem(musicbrainzId: string): Promise<{ success: boolean }> {
	return api.global.delete<{ success: boolean }>(`/api/v1/requests/history/${musicbrainzId}`);
}

export async function fetchActiveRequestCount(signal?: AbortSignal): Promise<number> {
	const data = await api.global.get<{ count?: number }>('/api/v1/requests/active/count', {
		signal
	});
	return data.count ?? 0;
}

export async function fetchPendingApprovals(signal?: AbortSignal): Promise<ActiveRequestsResponse> {
	return api.global.get<ActiveRequestsResponse>('/api/v1/requests/pending-approvals', { signal });
}

export async function approveRequest(musicbrainzId: string): Promise<{ success: boolean; message: string }> {
	return api.global.post<{ success: boolean; message: string }>(
		`/api/v1/requests/approve/${musicbrainzId}`
	);
}

export async function rejectRequest(musicbrainzId: string): Promise<{ success: boolean; message: string }> {
	return api.global.post<{ success: boolean; message: string }>(
		`/api/v1/requests/reject/${musicbrainzId}`
	);
}
