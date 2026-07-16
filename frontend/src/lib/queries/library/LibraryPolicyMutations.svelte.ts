import { createMutation } from '@tanstack/svelte-query';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type {
	LibraryPolicyApplyPreviewResponse,
	LibraryPolicyImpactResponse,
	TargetLibrarySettingsResponse,
	TypedLibrarySettings
} from './LibraryOperationsTypes';

async function invalidatePolicies(): Promise<void> {
	await Promise.all([
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.policyPrefix() }),
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.operationsPrefix() }),
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.activityPrefix() })
	]);
}

export function previewLibraryPolicyImpact() {
	return createMutation(() => ({
		mutationFn: (input: {
			settings: TypedLibrarySettings;
			expected_policy_revision: string | null;
		}) => api.global.post<LibraryPolicyImpactResponse>(API.library.policyImpact(), input)
	}));
}

export function saveTargetLibrarySettings() {
	return createMutation(() => ({
		mutationFn: (input: { settings: TypedLibrarySettings; expected_policy_revision: string }) =>
			api.global.put<TargetLibrarySettingsResponse>(API.library.settings(), input),
		onSuccess: async () => {
			await invalidatePolicies();
			toastStore.show({ message: 'Library policies saved', type: 'success' });
		},
		onError: () => toastStore.show({ message: 'Could not save library policies', type: 'error' })
	}));
}

export function previewLibraryPolicyApply() {
	return createMutation(() => ({
		mutationFn: (input: { scope_ids: string[]; expected_policy_revision: string }) =>
			api.global.post<LibraryPolicyApplyPreviewResponse>(API.library.policyApplyPreview(), input)
	}));
}
