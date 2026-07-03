export const SectionPrefsQueryKeyFactory = {
	prefix: ['section-prefs'] as const,
	// userId dimension: prefs are per-user and the cache persists across refreshes
	// on shared browsers.
	prefs: (userId: string | null | undefined) =>
		[...SectionPrefsQueryKeyFactory.prefix, userId ?? null] as const
};
