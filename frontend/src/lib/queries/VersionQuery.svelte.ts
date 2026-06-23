import { api } from '$lib/api/client';
import { API, CACHE_TTL } from '$lib/constants';
import { createQuery } from '@tanstack/svelte-query';
import { VersionQueryKeyFactory } from './VersionQueryKeyFactory';

interface VersionInfo {
	version: string;
	build_date: string | null;
}

export interface GitHubRelease {
	tag_name: string;
	name: string | null;
	body: string | null;
	published_at: string;
	html_url: string;
	prerelease: boolean;
}

interface UpdateCheckResponse {
	current_version: string;
	latest_version: string | null;
	update_available: boolean;
	comparison_failed: boolean;
	latest_release: GitHubRelease | null;
}

export const getVersionQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.VERSION_INFO,
		queryKey: VersionQueryKeyFactory.info(),
		queryFn: ({ signal }) => api.global.get<VersionInfo>(API.version.info(), { signal }),
		refetchOnWindowFocus: false,
		refetchOnMount: 'always'
	}));

export const getUpdateCheckQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.UPDATE_CHECK,
		queryKey: VersionQueryKeyFactory.updateCheck(),
		queryFn: ({ signal }) =>
			api.global.get<UpdateCheckResponse>(API.version.checkUpdate(), { signal }),
		refetchOnWindowFocus: false,
		refetchOnReconnect: false
	}));

export const getReleaseHistoryQuery = () =>
	createQuery(() => ({
		staleTime: CACHE_TTL.RELEASE_HISTORY,
		queryKey: VersionQueryKeyFactory.releases(),
		queryFn: ({ signal }) => api.global.get<GitHubRelease[]>(API.version.releases(), { signal }),
		refetchOnWindowFocus: false,
		refetchOnReconnect: false
	}));
