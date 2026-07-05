import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { authStore } from '$lib/stores/authStore.svelte';
import { FollowQueryKeyFactory } from './FollowQueryKeyFactory';
import { FOLLOW_ENDPOINTS } from './endpoints';
import type {
	FollowStatus,
	FollowedArtist,
	NewReleasesResponse,
	UnseenCountResponse
} from './types';

type Getter<T> = () => T;

export const getFollowStatusQuery = (getMbid: Getter<string>) =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.status(getMbid(), authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<FollowStatus>(FOLLOW_ENDPOINTS.status(getMbid()), { signal })
	}));

export const getFollowedArtistsQuery = () =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.artists(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<FollowedArtist[]>(FOLLOW_ENDPOINTS.followedArtists(), { signal })
	}));

export const getNewReleasesQuery = (getLimit: Getter<number>, getOffset: Getter<number>) =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.newReleases(authStore.user?.id, getLimit(), getOffset()),
		queryFn: ({ signal }) =>
			api.global.get<NewReleasesResponse>(FOLLOW_ENDPOINTS.newReleases(getLimit(), getOffset()), {
				signal
			})
	}));

// drives the sidebar badge; the feed only changes when the daily poller runs,
// so a slow interval (plus refetch-on-focus) is plenty
export const getUnseenNewReleasesCountQuery = () =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.newReleasesUnseen(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<UnseenCountResponse>(FOLLOW_ENDPOINTS.newReleasesUnseenCount(), { signal }),
		enabled: !!authStore.user?.id,
		refetchInterval: 60_000
	}));
