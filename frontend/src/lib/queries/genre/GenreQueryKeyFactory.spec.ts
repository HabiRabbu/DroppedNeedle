import { describe, expect, it } from 'vitest';
import { GenreQueryKeyFactory } from './GenreQueryKeyFactory';

describe('GenreQueryKeyFactory', () => {
	it('normalizes spelling while isolating persisted data by user', () => {
		expect(GenreQueryKeyFactory.artistPages('user-1', '  LATIN ')).toEqual([
			'genre',
			'user-1',
			'latin',
			'artists'
		]);
		expect(GenreQueryKeyFactory.artistPages('user-2', 'Latin')).not.toEqual(
			GenreQueryKeyFactory.artistPages('user-1', 'Latin')
		);
	});
});
