import { describe, expect, it } from 'vitest';
import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';

describe('HomeQueryKeyFactory (AMU-5)', () => {
	it('prefix is [home]', () => {
		expect(HomeQueryKeyFactory.prefix).toEqual(['home']);
	});

	it('home key includes the userId dimension', () => {
		expect(HomeQueryKeyFactory.home('user-a', 'listenbrainz')).toEqual([
			'home',
			'user-a',
			'listenbrainz'
		]);
	});

	it('produces different keys for different users (no cross-user collision)', () => {
		const a = HomeQueryKeyFactory.home('user-a', 'listenbrainz');
		const b = HomeQueryKeyFactory.home('user-b', 'listenbrainz');
		expect(a).not.toEqual(b);
	});

	it('produces different keys for different sources', () => {
		const lb = HomeQueryKeyFactory.home('user-a', 'listenbrainz');
		const lfm = HomeQueryKeyFactory.home('user-a', 'lastfm');
		expect(lb).not.toEqual(lfm);
	});

	it('normalizes a missing userId to null', () => {
		expect(HomeQueryKeyFactory.home(undefined, 'listenbrainz')).toEqual([
			'home',
			null,
			'listenbrainz'
		]);
	});
});
