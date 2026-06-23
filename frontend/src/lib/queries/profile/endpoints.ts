import { API } from '$lib/constants';

/** Profile endpoints. The current user is resolved server-side from the session
 *  cookie, so none of these take a user id (the avatar GET is built per-user via
 *  `API.profile.avatar(userId)` directly where an <img> is rendered). */
export const PROFILE_ENDPOINTS = {
	get: API.profile.get(),
	update: API.profile.update(),
	avatarUpload: API.profile.avatarUpload(),
	updateUsername: API.profile.updateUsername(),
	updateEmail: API.profile.updateEmail(),
	changePassword: API.profile.changePassword(),
	setPassword: API.profile.setPassword()
} as const;
