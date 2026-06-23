import { api } from '$lib/api/client';
import { createMutation } from '@tanstack/svelte-query';
import { toAuthUser, type AuthSessionUser } from '$lib/queries/auth/types';
import { authStore } from '$lib/stores/authStore.svelte';
import { invalidateQueriesWithPersister } from '../QueryClient';
import { ProfileQueryKeyFactory } from './ProfileQueryKeyFactory';
import { PROFILE_ENDPOINTS } from './endpoints';
import type {
	ChangePasswordVars,
	DisplayNameUpdateVars,
	EmailUpdateVars,
	SetPasswordVars,
	UsernameUpdateVars
} from './types';

/**
 * Profile self-service mutations (D8). Each returns the updated user
 * (`UserResponse`, incl. providers), so on success we sync `authStore` - keeping
 * the topbar name/avatar and the change-vs-set-password branch correct - and
 * invalidate the user-scoped profile query so the card refreshes (AMU-5).
 */
async function applyUser(userId: string, user: AuthSessionUser): Promise<void> {
	authStore.setUser(toAuthUser(user));
	await invalidateQueriesWithPersister({ queryKey: ProfileQueryKeyFactory.profile(userId) });
}

export const createUpdateDisplayNameMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (vars: DisplayNameUpdateVars) =>
			api.global.put<AuthSessionUser>(PROFILE_ENDPOINTS.update, vars),
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));

export const createUpdateUsernameMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (vars: UsernameUpdateVars) =>
			api.global.put<AuthSessionUser>(PROFILE_ENDPOINTS.updateUsername, vars),
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));

export const createUpdateEmailMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (vars: EmailUpdateVars) =>
			api.global.put<AuthSessionUser>(PROFILE_ENDPOINTS.updateEmail, vars),
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));

export const createChangePasswordMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (vars: ChangePasswordVars) =>
			api.global.post<AuthSessionUser>(PROFILE_ENDPOINTS.changePassword, vars),
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));

export const createSetPasswordMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (vars: SetPasswordVars) =>
			api.global.post<AuthSessionUser>(PROFILE_ENDPOINTS.setPassword, vars),
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));

export const createUploadAvatarMutation = (userId: string) =>
	createMutation(() => ({
		mutationFn: (file: File) => {
			const form = new FormData();
			form.append('file', file);
			return api.global.upload<AuthSessionUser>(PROFILE_ENDPOINTS.avatarUpload, form);
		},
		onSuccess: (user: AuthSessionUser) => applyUser(userId, user)
	}));
