import { describe, expect, it } from 'vitest';
import { DiscoverQueryKeyFactory } from './DiscoverQueryKeyFactory';

describe('DiscoverQueryKeyFactory (AMU-5)', () => {
	it('prefix is [discover]', () => {
		expect(DiscoverQueryKeyFactory.prefix).toEqual(['discover']);
	});

	describe('discover', () => {
		it('includes userId', () => {
			expect(DiscoverQueryKeyFactory.discover('user-a')).toEqual(['discover', 'user-a']);
		});

		it('differs per user (no cross-user collision)', () => {
			expect(DiscoverQueryKeyFactory.discover('user-a')).not.toEqual(
				DiscoverQueryKeyFactory.discover('user-b')
			);
		});
	});

	describe('radio', () => {
		it('includes userId', () => {
			expect(DiscoverQueryKeyFactory.radio('user-a', 'artist', 'mbid-1')).toEqual([
				'discover',
				'user-a',
				'radio',
				'artist',
				'mbid-1'
			]);
		});

		it('differs per user', () => {
			expect(DiscoverQueryKeyFactory.radio('user-a', 'artist', 'mbid-1')).not.toEqual(
				DiscoverQueryKeyFactory.radio('user-b', 'artist', 'mbid-1')
			);
		});
	});

	describe('playlistSuggestions', () => {
		it('includes userId', () => {
			expect(DiscoverQueryKeyFactory.playlistSuggestions('user-a', 'pl-1')).toEqual([
				'discover',
				'user-a',
				'playlist-suggestions',
				'pl-1'
			]);
		});

		it('differs per user', () => {
			expect(DiscoverQueryKeyFactory.playlistSuggestions('user-a', 'pl-1')).not.toEqual(
				DiscoverQueryKeyFactory.playlistSuggestions('user-b', 'pl-1')
			);
		});
	});

	it('normalizes a missing userId to null', () => {
		expect(DiscoverQueryKeyFactory.discover(undefined)).toEqual(['discover', null]);
	});
});
