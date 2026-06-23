// userId dimension is mandatory (AMU-5): without it the persisted cache leaks one
// user's linked accounts to another on a shared browser
export const ConnectionsQueryKeyFactory = {
	prefix: ['me', 'connections'] as const,
	list: (userId: string | undefined) =>
		[...ConnectionsQueryKeyFactory.prefix, userId ?? 'anon'] as const
};
