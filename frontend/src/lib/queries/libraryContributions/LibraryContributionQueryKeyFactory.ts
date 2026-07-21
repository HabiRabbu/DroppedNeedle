export const LibraryContributionQueryKeyFactory = {
	root: (userId: string | undefined) => ['library-contributions', userId ?? 'anonymous'] as const,
	detail: (userId: string | undefined, contributionId: string) =>
		[...LibraryContributionQueryKeyFactory.root(userId), 'detail', contributionId] as const
};
