import { describe, expect, it } from 'vitest';
import { HomeQueryKeyFactory } from './HomeQueryKeyFactory';

describe('HomeQueryKeyFactory (AMU-5)', () => {
	it('prefix is [home]', () => {
		expect(HomeQueryKeyFactory.prefix).toEqual(['home']);
	});

	it('home key includes the userId dimension', () => {
		expect(HomeQueryKeyFactory.home('user-a')).toEqual(['home', 'user-a']);
	});

	it('produces different keys for different users (no cross-user collision)', () => {
		const a = HomeQueryKeyFactory.home('user-a');
		const b = HomeQueryKeyFactory.home('user-b');
		expect(a).not.toEqual(b);
	});

	it('normalizes a missing userId to null', () => {
		expect(HomeQueryKeyFactory.home(undefined)).toEqual(['home', null]);
	});
});
