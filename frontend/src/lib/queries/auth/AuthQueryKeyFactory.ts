export const AuthQueryKeyFactory = {
	prefix: ['auth'] as const,
	providers: () => [...AuthQueryKeyFactory.prefix, 'providers'] as const,
	/** Admin-only enumerated import candidates per provider. Kept under the `auth`
	 *  prefix so the login/logout cache-clear (AMU-5) covers it. */
	importCandidates: (provider: string) =>
		[...AuthQueryKeyFactory.prefix, 'import', provider] as const
};
