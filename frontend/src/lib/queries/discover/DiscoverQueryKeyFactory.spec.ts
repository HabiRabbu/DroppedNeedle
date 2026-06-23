import { describe, expect, it } from 'vitest';
import { DiscoverQueryKeyFactory } from './DiscoverQueryKeyFactory';

describe('DiscoverQueryKeyFactory (AMU-5)', () => {
	it('prefix is [discover]', () => {
		expect(DiscoverQueryKeyFactory.prefix).toEqual(['discover']);
	});

	describe('discover', () => {
		it('includes userId + source', () => {
			expect(DiscoverQueryKeyFactory.discover('user-a', 'listenbrainz')).toEqual([
				'discover',
				'user-a',
				'listenbrainz'
			]);
		});

		it('differs per user (no cross-user collision)', () => {
			expect(DiscoverQueryKeyFactory.discover('user-a', 'listenbrainz')).not.toEqual(
				DiscoverQueryKeyFactory.discover('user-b', 'listenbrainz')
			);
		});

		it('differs per source', () => {
			expect(DiscoverQueryKeyFactory.discover('user-a', 'listenbrainz')).not.toEqual(
				DiscoverQueryKeyFactory.discover('user-a', 'lastfm')
			);
		});
	});

	describe('radio', () => {
		it('includes userId', () => {
			expect(
				DiscoverQueryKeyFactory.radio('user-a', 'artist', 'mbid-1', 'listenbrainz')
			).toEqual(['discover', 'user-a', 'radio', 'artist', 'mbid-1', { source: 'listenbrainz' }]);
		});

		it('differs per user', () => {
			expect(
				DiscoverQueryKeyFactory.radio('user-a', 'artist', 'mbid-1', 'listenbrainz')
			).not.toEqual(DiscoverQueryKeyFactory.radio('user-b', 'artist', 'mbid-1', 'listenbrainz'));
		});
	});

	describe('playlistSuggestions', () => {
		it('includes userId and defaults source to null', () => {
			expect(DiscoverQueryKeyFactory.playlistSuggestions('user-a', 'pl-1')).toEqual([
				'discover',
				'user-a',
				'playlist-suggestions',
				'pl-1',
				null
			]);
		});

		it('differs per user', () => {
			expect(DiscoverQueryKeyFactory.playlistSuggestions('user-a', 'pl-1')).not.toEqual(
				DiscoverQueryKeyFactory.playlistSuggestions('user-b', 'pl-1')
			);
		});

		it('carries an explicit source', () => {
			expect(DiscoverQueryKeyFactory.playlistSuggestions('user-a', 'pl-1', 'lastfm')).toEqual([
				'discover',
				'user-a',
				'playlist-suggestions',
				'pl-1',
				'lastfm'
			]);
		});
	});

	it('normalizes a missing userId to null', () => {
		expect(DiscoverQueryKeyFactory.discover(undefined, 'listenbrainz')).toEqual([
			'discover',
			null,
			'listenbrainz'
		]);
	});
});
