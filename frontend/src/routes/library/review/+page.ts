import { redirect } from '@sveltejs/kit';
import { authStore } from '$lib/stores/authStore.svelte';

export const load = () => {
	if (!authStore.isAdmin) throw redirect(302, '/library');
	return {};
};
