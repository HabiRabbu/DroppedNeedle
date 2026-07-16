import { createInfiniteQuery, createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type {
	OperationResponse,
	ScanEstimateResponse,
	ScanRunCurrentResponse,
	ScanRunDetailResponse,
	ScanRunHistoryResponse
} from './LibraryOperationsTypes';

export const getCurrentLibraryRunsQueryOptions = () =>
	queryOptions({
		queryKey: LibraryQueryKeyFactory.currentRuns(),
		queryFn: ({ signal }) =>
			api.global.get<ScanRunCurrentResponse>(API.library.currentScanRuns(), { signal }),
		staleTime: 2_000
	});

export const getCurrentLibraryRunsQuery = (enabled: Getter<boolean> = () => true) =>
	createQuery(() => ({ ...getCurrentLibraryRunsQueryOptions(), enabled: enabled() }));

export const getLibraryRunQuery = (getRunId: Getter<string | null>) =>
	createQuery(() => {
		const runId = getRunId();
		return {
			enabled: Boolean(runId),
			queryKey: LibraryQueryKeyFactory.run(runId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<ScanRunDetailResponse>(API.library.scanRun(runId ?? ''), { signal })
		};
	});

export const getLibraryRunHistoryQuery = (enabled: Getter<boolean> = () => true) =>
	createInfiniteQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryQueryKeyFactory.runHistory(undefined),
		initialPageParam: undefined as string | undefined,
		queryFn: ({ pageParam, signal }) =>
			api.global.get<ScanRunHistoryResponse>(API.library.scanRuns(50, pageParam), { signal }),
		getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined
	}));

export const getLibraryRunEstimateQuery = (
	getScopeIds: Getter<string[]>,
	enabled: Getter<boolean>
) =>
	createQuery(() => {
		const scopeIds = getScopeIds();
		return {
			enabled: enabled(),
			queryKey: LibraryQueryKeyFactory.runEstimate(scopeIds),
			queryFn: ({ signal }) =>
				api.global.get<ScanEstimateResponse>(API.library.scanRunEstimate(scopeIds), { signal })
		};
	});

export const getLibraryOperationQuery = (getJobId: Getter<string | null>) =>
	createQuery(() => {
		const jobId = getJobId();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryQueryKeyFactory.repair(jobId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<OperationResponse>(API.library.operation(jobId ?? ''), { signal })
		};
	});
