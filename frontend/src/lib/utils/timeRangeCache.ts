// userId prefix isolates the time-range overview cache across users on a shared browser
// (not covered by the TanStack query-cache reset).
export function overviewCacheSuffix(
	userId: string | null | undefined,
	itemType: string,
	source: string | null | undefined,
	endpoint: string
): string {
	const uid = userId ?? 'anon';
	const sourceKey = source ?? 'none';
	return `${uid}:${itemType}:${sourceKey}:${encodeURIComponent(endpoint)}`;
}
