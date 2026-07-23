import { beforeEach, describe, expect, it, vi } from 'vitest';

const invalidate = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: invalidate
}));

import { invalidateLibraryManagementSurfaces } from './LibraryManagementInvalidation';

beforeEach(() => {
	vi.clearAllMocks();
});

describe('invalidateLibraryManagementSurfaces', () => {
	it('sweeps management, operation, catalog, artwork-bearing, genre and import caches', async () => {
		await invalidateLibraryManagementSurfaces();
		const keys = invalidate.mock.calls.map(([filters]) => filters.queryKey);

		expect(keys).toContainEqual(['library-management']);
		expect(keys).toContainEqual(['library', 'operations']);
		expect(keys).toContainEqual(['library']);
		expect(keys).toContainEqual(['local']);
		expect(keys).toContainEqual(['genre']);
		expect(keys).toContainEqual(['artist']);
		expect(keys).toContainEqual(['downloads']);
		expect(keys).toContainEqual(['drop-import']);
		expect(keys).toContainEqual(['free-music']);
	});
});
