export const ConnectAppsQueryKeyFactory = {
	all: ['connect-apps'] as const,
	settings: () => [...ConnectAppsQueryKeyFactory.all, 'settings'] as const,
	appPasswords: () => [...ConnectAppsQueryKeyFactory.all, 'app-passwords'] as const
};
