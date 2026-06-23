import { writable } from 'svelte/store';
import type { UserPreferences } from '$lib/types';
import { api } from '$lib/api/client';

const API_BASE = '/api/v1';

const defaultPreferences: UserPreferences = {
	primary_types: ['album', 'ep', 'single'],
	secondary_types: ['studio']
};

const { subscribe, set, update } = writable<UserPreferences>(defaultPreferences);

async function loadPreferences(): Promise<void> {
	try {
		const prefs = await api.global.get<UserPreferences>(`${API_BASE}/settings/preferences`);
		set(prefs);
	} catch {
		// use defaults on fetch failure
	}
}

async function savePreferences(prefs: UserPreferences): Promise<boolean> {
	try {
		const updated = await api.global.put<UserPreferences>(
			`${API_BASE}/settings/preferences`,
			prefs
		);
		set(updated);
		return true;
	} catch {
		return false;
	}
}

export const preferencesStore = {
	subscribe,
	load: loadPreferences,
	save: savePreferences,
	update
};
