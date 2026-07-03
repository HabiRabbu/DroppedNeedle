export const HomeQueryKeyFactory = {
	prefix: ['home'] as const,
	// userId dimension isolates one user's home cache from another's on a shared browser.
	home: (userId: string | null | undefined) =>
		[...HomeQueryKeyFactory.prefix, userId ?? null] as const
};
