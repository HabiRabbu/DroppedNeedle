import { redirect } from '@sveltejs/kit';
import { authStore } from '$lib/stores/authStore.svelte';

// ssr=false (root layout) → this runs client-side after the layout has hydrated
// authStore, so the admin check is reliable.
export const load = () => {
	if (!authStore.isAdmin) {
		throw redirect(302, '/library');
	}
	return {};
};
