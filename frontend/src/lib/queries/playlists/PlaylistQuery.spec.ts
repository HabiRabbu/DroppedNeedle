import { describe, expect, it } from 'vitest';
import { PlaylistQueryKeyFactory } from './PlaylistQueryKeyFactory';

// Playlist query keys carry the current user id so personalized data never leaks
// across a user switch on a shared browser (AMU-5).
describe('PlaylistQueryKeyFactory', () => {
	it('list key includes the user id', () => {
		expect(PlaylistQueryKeyFactory.list('user-1')).toEqual(['playlists', 'user-1', 'list']);
	});

	it('detail key includes the user id and the playlist id', () => {
		expect(PlaylistQueryKeyFactory.detail('user-1', 'pl-9')).toEqual([
			'playlists',
			'user-1',
			'detail',
			'pl-9'
		]);
	});

	it('different users produce different list keys (cache isolation)', () => {
		expect(PlaylistQueryKeyFactory.list('a')).not.toEqual(PlaylistQueryKeyFactory.list('b'));
	});

	it('different users produce different detail keys for the same playlist', () => {
		expect(PlaylistQueryKeyFactory.detail('a', 'pl-1')).not.toEqual(
			PlaylistQueryKeyFactory.detail('b', 'pl-1')
		);
	});

	it('falls back to anon when the user id is undefined', () => {
		expect(PlaylistQueryKeyFactory.list(undefined)).toEqual(['playlists', 'anon', 'list']);
		expect(PlaylistQueryKeyFactory.detail(undefined, 'pl-1')).toEqual([
			'playlists',
			'anon',
			'detail',
			'pl-1'
		]);
	});
});
