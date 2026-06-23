import { describe, expect, it } from 'vitest';
import { overviewCacheSuffix } from '$lib/utils/timeRangeCache';

// The suffix must be user-scoped so the (non-TanStack) overview cache can't leak across users.
describe('TimeRangeView overview cache suffix (AMU-5)', () => {
	it('prefixes the suffix with the user id', () => {
		const suffix = overviewCacheSuffix(
			'user-a',
			'album',
			'listenbrainz',
			'/api/v1/home/your-top/albums'
		);
		expect(suffix.startsWith('user-a:')).toBe(true);
	});

	it('differs per user for the same item / source / endpoint', () => {
		const a = overviewCacheSuffix('user-a', 'album', 'listenbrainz', '/x');
		const b = overviewCacheSuffix('user-b', 'album', 'listenbrainz', '/x');
		expect(a).not.toEqual(b);
	});

	it('falls back to anon when the user id is missing', () => {
		expect(overviewCacheSuffix(undefined, 'artist', null, '/x').startsWith('anon:')).toBe(true);
	});

	it('encodes the endpoint', () => {
		const suffix = overviewCacheSuffix('user-a', 'album', 'lastfm', '/a/b?x=1');
		expect(suffix).toContain(encodeURIComponent('/a/b?x=1'));
	});
});
