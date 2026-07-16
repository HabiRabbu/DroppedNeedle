import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import type { NavidromeFolderPreference, NavidromeFolderPreferenceUpdate } from '$lib/types';
import {
	clearNavidromeLocalCaches,
	setNavidromeFolderScopeRevision
} from '$lib/utils/navidromeLibraryCache';
import { createMutation } from '@tanstack/svelte-query';
import { LibraryQueryKeyFactory } from '../library/LibraryQueryKeyFactory';
import { NavidromeFolderQueryKeyFactory } from './NavidromeFolderQueryKeyFactory';

export const createUpdateNavidromeFolderPreferenceMutation = (getUserId: () => string) =>
	createMutation(() => ({
		mutationFn: (body: NavidromeFolderPreferenceUpdate) =>
			api.global.put<NavidromeFolderPreference>(API.me.navidromeMusicFolderPreferences(), body),
		onSuccess: async (result) => {
			clearNavidromeLocalCaches();
			setNavidromeFolderScopeRevision(getUserId(), result.scope_revision);
			await Promise.all([
				invalidateQueriesWithPersister({
					queryKey: NavidromeFolderQueryKeyFactory.preferences(getUserId())
				}),
				invalidateQueriesWithPersister({
					queryKey: NavidromeFolderQueryKeyFactory.catalogPrefix(getUserId())
				}),
				invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all })
			]);
		}
	}));
