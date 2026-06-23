// userId scopes every key (AMU-5): without it the persisted cache leaks one
// user's follows to another on a shared browser.
export const FollowQueryKeyFactory = {
	statusPrefix: ['follow', 'status'] as const,
	followingPrefix: ['following'] as const,
	status: (mbid: string, userId: string | undefined) =>
		[...FollowQueryKeyFactory.statusPrefix, mbid, userId ?? 'anon'] as const,
	artists: (userId: string | undefined) =>
		[...FollowQueryKeyFactory.followingPrefix, 'artists', userId ?? 'anon'] as const,
	newReleases: (userId: string | undefined, limit: number, offset: number) =>
		[
			...FollowQueryKeyFactory.followingPrefix,
			'new-releases',
			userId ?? 'anon',
			limit,
			offset
		] as const,
	// admin queue is global (not per-user) - admins review every pending grant
	adminApprovals: () => [...FollowQueryKeyFactory.followingPrefix, 'admin-approvals'] as const
};
