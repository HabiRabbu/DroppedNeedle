import { api } from '$lib/api/client';
import { API, AUTH_FREE_PATHS } from '$lib/constants';
import { DEFAULT_SOURCE, isMusicSource } from '$lib/stores/musicSource';
import { authStore } from '$lib/stores/authStore.svelte';
import { redirect } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: LayoutLoad = async ({ url }) => {
	const path = url.pathname;
	const isAuthFree = AUTH_FREE_PATHS.some((p) => path.startsWith(p));

	// Check whether first-run setup is needed
	let setupRequired = false;
	try {
		const status = await api.global.get<{ required: boolean }>('/api/v1/auth/setup/status');
		setupRequired = status.required;
	} catch {
		// Backend unreachable, let the page handle it
	}

	if (setupRequired && !isAuthFree) {
		throw redirect(302, '/setup');
	}

	// Hydrate auth state by asking the backend to validate the session cookie.
	// The cookie is sent automatically via credentials: 'include' in client.ts.
	if (!authStore.initialized) {
		try {
			const user = await api.global.get<{
				id: string;
				display_name: string;
				role: string;
				email: string | null;
				avatar_url: string | null;
			}>('/api/v1/auth/me');
			authStore.setUser({
				id: user.id,
				display_name: user.display_name,
				role: user.role as 'admin' | 'trusted' | 'user',
				email: user.email,
				avatar_url: user.avatar_url
			});
		} catch {
			// No valid session, authStore.user remains null
			authStore.clear();
		}
		authStore.markInitialized();
	}

	if (!setupRequired && !isAuthFree && !authStore.isAuthenticated) {
		throw redirect(302, '/login');
	}

	let primarySource = DEFAULT_SOURCE;
	try {
		const data = await api.global.get<{ source: unknown }>(API.settingsPrimarySource());
		if (isMusicSource(data.source)) primarySource = data.source;
	} catch {
		// ignore
	}

	return { primarySource };
};
