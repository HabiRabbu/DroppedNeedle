import { createInfiniteQuery, createQuery, queryOptions } from '@tanstack/svelte-query';
import type { Getter } from 'runed';

import { api } from '$lib/api/client';
import { API } from '$lib/constants';

import { LibraryManagementQueryKeyFactory } from './LibraryManagementQueryKeyFactory';
import type {
	LibraryManagementHistoryParams,
	LibraryManagementOperationHistoryResponse,
	LibraryManagementPlanItemPageResponse,
	LibraryManagementPlanItemParams,
	LibraryManagementPresetDiff,
	LibraryManagementPreviewDetailResponse,
	LibraryManagementProfile,
	LibraryManagementRecoveryDiagnosticsResponse,
	LibraryManagementResultPageResponse,
	LibraryManagementSettingsResponse,
	LibraryManagementTagEditorContext
} from './types';

export const getLibraryManagementSettingsQueryOptions = (userId: string | null | undefined) =>
	queryOptions({
		queryKey: LibraryManagementQueryKeyFactory.settings(userId),
		queryFn: ({ signal }) =>
			api.global.get<LibraryManagementSettingsResponse>(API.libraryManagement.settings(), {
				signal
			})
	});

export const getLibraryManagementSettingsQuery = (
	getUserId: Getter<string | null | undefined>,
	enabled: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		...getLibraryManagementSettingsQueryOptions(getUserId()),
		enabled: enabled()
	}));

export const getLibraryManagementTagEditorQuery = (
	getUserId: Getter<string | null | undefined>,
	getTrackId: Getter<string | null>,
	enabled: Getter<boolean> = () => true
) =>
	createQuery(() => {
		const trackId = getTrackId();
		return {
			enabled: enabled() && Boolean(trackId),
			queryKey: LibraryManagementQueryKeyFactory.tagEditor(getUserId(), trackId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementTagEditorContext>(
					API.libraryManagement.tagEditor(trackId ?? ''),
					{ signal }
				)
		};
	});

export const getLibraryManagementProfileQuery = (
	getUserId: Getter<string | null | undefined>,
	getProfileId: Getter<string | null>
) =>
	createQuery(() => {
		const profileId = getProfileId();
		return {
			enabled: Boolean(profileId),
			queryKey: LibraryManagementQueryKeyFactory.profile(getUserId(), profileId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementProfile>(API.libraryManagement.profile(profileId ?? ''), {
					signal
				})
		};
	});

export const getLibraryManagementPresetDiffQuery = (
	getUserId: Getter<string | null | undefined>,
	getProfileId: Getter<string | null>
) =>
	createQuery(() => {
		const profileId = getProfileId();
		return {
			enabled: Boolean(profileId),
			queryKey: LibraryManagementQueryKeyFactory.presetDiff(getUserId(), profileId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementPresetDiff>(
					API.libraryManagement.profilePresetDiff(profileId ?? ''),
					{ signal }
				)
		};
	});

export const getLibraryManagementActivationPreviewQuery = (
	getUserId: Getter<string | null | undefined>,
	getJobId: Getter<string | null>
) =>
	createQuery(() => {
		const jobId = getJobId();
		return {
			enabled: Boolean(jobId),
			refetchInterval: jobId ? 2000 : false,
			queryKey: LibraryManagementQueryKeyFactory.activationPreview(getUserId(), jobId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementPreviewDetailResponse>(
					API.libraryManagement.activationPreview(jobId ?? ''),
					{ signal }
				)
		};
	});

export const getLibraryManagementPreviewQuery = (
	getUserId: Getter<string | null | undefined>,
	getJobId: Getter<string | null>
) =>
	createQuery(() => {
		const jobId = getJobId();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryManagementQueryKeyFactory.preview(getUserId(), jobId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementPreviewDetailResponse>(
					API.libraryManagement.preview(jobId ?? ''),
					{ signal }
				)
		};
	});

export const getLibraryManagementPlanItemsQuery = (
	getUserId: Getter<string | null | undefined>,
	getJobId: Getter<string | null>,
	getParams: Getter<LibraryManagementPlanItemParams> = () => ({})
) =>
	createInfiniteQuery(() => {
		const jobId = getJobId();
		const params = getParams();
		const limit = params.limit ?? 100;
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryManagementQueryKeyFactory.previewItems(getUserId(), jobId ?? '', params),
			initialPageParam: -1,
			queryFn: ({ pageParam, signal }) =>
				api.global.get<LibraryManagementPlanItemPageResponse>(
					API.libraryManagement.previewItems(jobId ?? '', {
						...params,
						afterOrdinal: pageParam,
						limit
					}),
					{ signal }
				),
			getNextPageParam: (lastPage: LibraryManagementPlanItemPageResponse) =>
				lastPage.has_more ? (lastPage.next_after_ordinal ?? undefined) : undefined
		};
	});

export const getLibraryManagementOperationsQuery = (
	getUserId: Getter<string | null | undefined>,
	getParams: Getter<LibraryManagementHistoryParams> = () => ({})
) =>
	createInfiniteQuery(() => {
		const params = getParams();
		return {
			queryKey: LibraryManagementQueryKeyFactory.operations(getUserId(), params),
			initialPageParam: undefined as string | undefined,
			queryFn: ({ pageParam, signal }) =>
				api.global.get<LibraryManagementOperationHistoryResponse>(
					API.libraryManagement.operations({ ...params, cursor: pageParam }),
					{ signal }
				),
			getNextPageParam: (lastPage: LibraryManagementOperationHistoryResponse) =>
				lastPage.next_cursor ?? undefined
		};
	});

export const getLibraryManagementOperationQuery = (
	getUserId: Getter<string | null | undefined>,
	getJobId: Getter<string | null>
) =>
	createQuery(() => {
		const jobId = getJobId();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryManagementQueryKeyFactory.operation(getUserId(), jobId ?? ''),
			queryFn: ({ signal }) =>
				api.global.get<LibraryManagementPreviewDetailResponse>(
					API.libraryManagement.operation(jobId ?? ''),
					{ signal }
				)
		};
	});

export const getLibraryManagementOperationResultsQuery = (
	getUserId: Getter<string | null | undefined>,
	getJobId: Getter<string | null>,
	getLimit: Getter<number> = () => 100
) =>
	createInfiniteQuery(() => {
		const jobId = getJobId();
		const limit = getLimit();
		return {
			enabled: Boolean(jobId),
			queryKey: LibraryManagementQueryKeyFactory.operationResults(getUserId(), jobId ?? '', limit),
			initialPageParam: -1,
			queryFn: ({ pageParam, signal }) =>
				api.global.get<LibraryManagementResultPageResponse>(
					API.libraryManagement.operationResults(jobId ?? '', pageParam, limit),
					{ signal }
				),
			getNextPageParam: (lastPage: LibraryManagementResultPageResponse) =>
				lastPage.has_more ? (lastPage.next_after_ordinal ?? undefined) : undefined
		};
	});

export const getLibraryManagementRecoveryQuery = (
	getUserId: Getter<string | null | undefined>,
	enabled: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryManagementQueryKeyFactory.recovery(getUserId()),
		queryFn: ({ signal }) =>
			api.global.get<LibraryManagementRecoveryDiagnosticsResponse>(
				API.libraryManagement.recoveryDiagnostics(),
				{ signal }
			)
	}));
