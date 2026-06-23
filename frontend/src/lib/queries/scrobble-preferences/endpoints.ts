import { API } from '$lib/constants';

export const SCROBBLE_PREFERENCES_ENDPOINTS = {
	get: API.me.scrobblePreferences(),
	update: API.me.scrobblePreferences()
} as const;
