import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type {
	OperationListResponse,
	OperationResponse,
	RepairEstimateResponse,
	RepairFindingListResponse
} from './LibraryOperationsTypes';

export const getLibraryRepairsQuery = (enabled: Getter<boolean> = () => true) =>
	createInfiniteQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryQueryKeyFactory.repairs(undefined),
		initialPageParam: undefined as string | undefined,
		queryFn: ({ pageParam, signal }) =>
			api.global.get<OperationListResponse>(API.library.identityRepairs(50, pageParam), { signal }),
		getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined
	}));

export const getLibraryRepairQuery = (getJobId: Getter<string | null>) =>
	createQuery(() => {
		const jobId = getJobId();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryQueryKeyFactory.repair(jobId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<OperationResponse>(API.library.identityRepair(jobId ?? ''), { signal })
		};
	});

export const getLibraryRepairEstimateQuery = (
	getRootIds: Getter<string[]>,
	enabled: Getter<boolean>
) =>
	createQuery(() => {
		const rootIds = getRootIds();
		return {
			enabled: enabled(),
			queryKey: LibraryQueryKeyFactory.repairEstimate(rootIds),
			queryFn: ({ signal }) =>
				api.global.get<RepairEstimateResponse>(API.library.identityRepairEstimate(rootIds), {
					signal
				})
		};
	});

export const getLibraryRepairFindingsQuery = (
	getJobId: Getter<string | null>,
	getFindingCategory: Getter<string>
) =>
	createInfiniteQuery(() => {
		const jobId = getJobId();
		const findingCategory = getFindingCategory();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryQueryKeyFactory.repairFindings(jobId ?? '', findingCategory, undefined),
			initialPageParam: undefined as string | undefined,
			queryFn: ({ pageParam, signal }) =>
				api.global.get<RepairFindingListResponse>(
					API.library.identityRepairFindings(jobId ?? '', 100, pageParam, findingCategory),
					{ signal }
				),
			getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined
		};
	});
