import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { authStore } from '$lib/stores/authStore.svelte';
import { FollowQueryKeyFactory } from './FollowQueryKeyFactory';
import { FOLLOW_ENDPOINTS } from './endpoints';
import type {
	CitySearchResponse,
	ConcertsResponse,
	EventCitiesResponse,
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

// the release LOG (owned albums included, flagged in_library; include_owned=false
// is the page's hide-owned filter, matching the GET /new-releases to-do view)
export const getRecentReleasesQuery = (
	getDays: Getter<number>,
	getLimit: Getter<number>,
	getIncludeOwned: Getter<boolean> = () => true
) =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.recentReleases(
			authStore.user?.id,
			getDays(),
			getLimit(),
			getIncludeOwned()
		),
		queryFn: ({ signal }) =>
			api.global.get<NewReleasesResponse>(
				FOLLOW_ENDPOINTS.recentReleases(getDays(), getLimit(), getIncludeOwned()),
				{ signal }
			)
	}));

export const getConcertsQuery = () =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.concerts(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<ConcertsResponse>(FOLLOW_ENDPOINTS.concerts(), { signal })
	}));

export const getEventCitiesQuery = () =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.concertCities(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<EventCitiesResponse>(FOLLOW_ENDPOINTS.concertCities(), { signal })
	}));

// enabled only from 2 chars (the backend's min query length); callers debounce
export const getCitySearchQuery = (getQ: Getter<string>) =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.citySearch(authStore.user?.id, getQ()),
		queryFn: ({ signal }) =>
			api.global.get<CitySearchResponse>(FOLLOW_ENDPOINTS.concertCitySearch(getQ()), { signal }),
		enabled: getQ().trim().length >= 2
	}));

// drives the concerts half of the sidebar badge pair (same cadence rationale
// as the new-releases badge below)
export const getUnseenConcertsCountQuery = () =>
	createQuery(() => ({
		queryKey: FollowQueryKeyFactory.concertsUnseen(authStore.user?.id),
		queryFn: ({ signal }) =>
			api.global.get<UnseenCountResponse>(FOLLOW_ENDPOINTS.concertsUnseenCount(), { signal }),
		enabled: !!authStore.user?.id,
		refetchInterval: 60_000
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
