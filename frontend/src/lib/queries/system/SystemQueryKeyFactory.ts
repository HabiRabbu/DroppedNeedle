export const SystemQueryKeyFactory = {
	prefix: ['system'] as const,
	// no userId dimension: service health is global, not per-user
	health: () => [...SystemQueryKeyFactory.prefix, 'health'] as const
};
