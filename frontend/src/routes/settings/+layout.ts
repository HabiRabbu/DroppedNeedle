import { authStore } from '$lib/stores/authStore.svelte';
import { redirect } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

export const ssr = false;

export const load: LayoutLoad = () => {
	if (!authStore.isAdmin) {
		throw redirect(302, '/');
	}
};
