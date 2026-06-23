/** Auth endpoints. Login/setup happen before a session exists, so those are
 * called via the unauthenticated `api.global` client. The `adminImport*`
 * endpoints are post-session admin actions and use the authenticated `api`
 * client instead. */
export const AUTH_ENDPOINTS = {
	providers: '/api/v1/auth/providers',
	login: '/api/v1/auth/login',
	jellyfinLogin: '/api/v1/auth/jellyfin/login',
	setup: '/api/v1/auth/setup',
	oidcAuthorize: '/api/v1/auth/oidc/authorize',
	oidcExchange: '/api/v1/auth/oidc/exchange',
	plexPin: '/api/v1/auth/plex/pin',
	plexPoll: (pinId: string) => `/api/v1/auth/plex/poll?pin_id=${encodeURIComponent(pinId)}`,
	adminImportJellyfin: '/api/v1/auth/admin/import/jellyfin',
	adminImportPlex: '/api/v1/auth/admin/import/plex',
	adminImport: '/api/v1/auth/admin/import'
} as const;
