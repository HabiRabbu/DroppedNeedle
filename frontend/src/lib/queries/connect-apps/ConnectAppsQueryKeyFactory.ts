export const ConnectAppsQueryKeyFactory = {
	all: ['connect-apps'] as const,
	settings: () => [...ConnectAppsQueryKeyFactory.all, 'settings'] as const,
	// per-user: the userId segment keeps one user's list off another's on a shared
	// browser (IndexedDB persists across refresh); required arg = no silent key miss.
	appPasswords: (userId: string) =>
		[...ConnectAppsQueryKeyFactory.all, userId, 'app-passwords'] as const,
	// admin oversight roster is viewer-independent (same for every admin) -> no userId
	adminAppPasswords: () => [...ConnectAppsQueryKeyFactory.all, 'admin', 'app-passwords'] as const
};
