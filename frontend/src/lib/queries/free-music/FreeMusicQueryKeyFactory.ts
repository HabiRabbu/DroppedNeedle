// Tasks are user-scoped (each user sees their own; admins can see all), so the key
// carries the userId segment - the IndexedDB-persisted cache must never show one
// user's downloads to another on a shared browser.
export const FreeMusicQueryKeyFactory = {
	prefix: ['free-music'] as const,
	tasks: (userId: string | undefined, all: boolean) =>
		[...FreeMusicQueryKeyFactory.prefix, 'tasks', userId ?? 'anon', { all }] as const
};
