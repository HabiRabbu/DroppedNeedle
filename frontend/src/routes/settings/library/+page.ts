import { redirect } from '@sveltejs/kit';
import { authStore } from '$lib/stores/authStore.svelte';

// Library settings moved into the consolidated Settings → Library tab.
export const load = () => {
	if (!authStore.isAdmin) {
		throw redirect(302, '/');
	}
	throw redirect(307, '/settings?tab=library');
};
