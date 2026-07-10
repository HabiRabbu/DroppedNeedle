// Plugin list/config is global admin state, not user-dependent, so no userId segment.
export const PluginQueryKeyFactory = {
	prefix: ['plugins'] as const,
	list: () => [...PluginQueryKeyFactory.prefix, 'list'] as const
};
