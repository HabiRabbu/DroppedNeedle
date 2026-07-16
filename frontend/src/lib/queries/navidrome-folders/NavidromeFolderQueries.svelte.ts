import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import type { NavidromeFolderPreference } from '$lib/types';
import { createQuery } from '@tanstack/svelte-query';
import { NavidromeFolderQueryKeyFactory } from './NavidromeFolderQueryKeyFactory';
import { setNavidromeFolderScopeRevision } from '$lib/utils/navidromeLibraryCache';

export const getNavidromeFolderPreferenceQuery = (getUserId: () => string) =>
	createQuery(() => ({
		queryKey: NavidromeFolderQueryKeyFactory.preferences(getUserId()),
		queryFn: async ({ signal }) => {
			const result = await api.global.get<NavidromeFolderPreference>(
				API.me.navidromeMusicFolderPreferences(),
				{ signal }
			);
			setNavidromeFolderScopeRevision(getUserId(), result.scope_revision);
			return result;
		},
		enabled: Boolean(getUserId())
	}));
