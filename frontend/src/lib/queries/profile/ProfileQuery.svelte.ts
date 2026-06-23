import { api } from '$lib/api/client';
import { createQuery } from '@tanstack/svelte-query';
import { ProfileQueryKeyFactory } from './ProfileQueryKeyFactory';
import { PROFILE_ENDPOINTS } from './endpoints';
import type { ProfileData } from './types';

/** The current user's profile. Keyed by `userId` so the cache never leaks across
 *  users on a shared browser (AMU-5). */
export const getProfileQuery = (userId: string) =>
	createQuery(() => ({
		queryKey: ProfileQueryKeyFactory.profile(userId),
		queryFn: ({ signal }) => api.global.get<ProfileData>(PROFILE_ENDPOINTS.get, { signal })
	}));
