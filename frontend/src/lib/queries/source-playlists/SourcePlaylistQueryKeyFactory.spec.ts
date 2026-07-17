import { describe, expect, it } from 'vitest';

import { SourcePlaylistQueryKeyFactory } from './SourcePlaylistQueryKeyFactory';

describe('SourcePlaylistQueryKeyFactory', () => {
	it('separates persisted playlist data by DroppedNeedle user', () => {
		expect(SourcePlaylistQueryKeyFactory.list('alice', 'jellyfin', 200)).not.toEqual(
			SourcePlaylistQueryKeyFactory.list('bob', 'jellyfin', 200)
		);
	});

	it('separates providers and nests detail under the user and source prefix', () => {
		expect(SourcePlaylistQueryKeyFactory.detail('alice', 'plex', 'playlist-1')).toEqual([
			'source-playlists',
			'alice',
			'plex',
			'detail',
			'playlist-1'
		]);
		expect(SourcePlaylistQueryKeyFactory.source('alice', 'navidrome')).not.toEqual(
			SourcePlaylistQueryKeyFactory.source('alice', 'plex')
		);
	});
});
