import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { FollowQueryKeyFactory } from './FollowQueryKeyFactory';
import { FOLLOW_ENDPOINTS } from './endpoints';
import type { AutoDownloadApprovalsResponse } from './types';

type Getter<T> = () => T;

export const getAutoDownloadApprovalsQuery = (getEnabled: Getter<boolean>) =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.adminApprovals(),
		queryFn: ({ signal }) =>
			api.global.get<AutoDownloadApprovalsResponse>(FOLLOW_ENDPOINTS.adminApprovals(), { signal }),
		enabled: getEnabled()
	}));
