export const NavidromeFolderQueryKeyFactory = {
	prefix: ['navidrome'] as const,
	preferences: (userId: string) =>
		[...NavidromeFolderQueryKeyFactory.prefix, 'folder-preferences', userId] as const,
	catalogPrefix: (userId: string) =>
		[...NavidromeFolderQueryKeyFactory.prefix, 'catalog', userId] as const,
	catalog: (userId: string, scopeRevision: string) =>
		[...NavidromeFolderQueryKeyFactory.catalogPrefix(userId), scopeRevision] as const
};
