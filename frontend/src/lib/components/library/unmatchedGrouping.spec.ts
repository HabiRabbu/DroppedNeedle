import { describe, expect, it } from 'vitest';
import type { ManualReviewEntry } from '$lib/types';
import { groupUnmatched } from './unmatchedGrouping';

function mk(
	partial: Partial<ManualReviewEntry> & { id: number; file_path: string }
): ManualReviewEntry {
	return {
		extracted_title: null,
		extracted_artist: null,
		extracted_album: null,
		extracted_year: null,
		track_number: null,
		disc_number: null,
		file_format: 'flac',
		duration: null,
		file_size: null,
		fingerprint: null,
		fingerprint_score: null,
		candidate_mbids: [],
		source: 'text_match',
		created_at: null,
		...partial
	};
}

describe('groupUnmatched', () => {
	it('clusters files by their parent folder', () => {
		const groups = groupUnmatched([
			mk({ id: 1, file_path: '/music/OK Computer/01.flac' }),
			mk({ id: 2, file_path: '/music/OK Computer/02.flac' }),
			mk({ id: 3, file_path: '/music/Kid A/01.flac' })
		]);
		expect(groups).toHaveLength(2);
		const ok = groups.find((g) => g.folder === '/music/OK Computer');
		expect(ok?.files.map((f) => f.id)).toEqual([1, 2]);
		expect(ok?.folderName).toBe('OK Computer');
	});

	it('guesses album + artist from the most common tags in the folder', () => {
		const [group] = groupUnmatched([
			mk({
				id: 1,
				file_path: '/m/a/1.flac',
				extracted_album: 'OK Computer',
				extracted_artist: 'Radiohead'
			}),
			mk({
				id: 2,
				file_path: '/m/a/2.flac',
				extracted_album: 'OK Computer',
				extracted_artist: 'Radiohead'
			}),
			mk({ id: 3, file_path: '/m/a/3.flac', extracted_album: null, extracted_artist: 'Radiohead' })
		]);
		expect(group.guessedAlbum).toBe('OK Computer');
		expect(group.guessedArtist).toBe('Radiohead');
	});

	it('orders groups by file count and files by track number', () => {
		const groups = groupUnmatched([
			mk({ id: 1, file_path: '/m/small/1.flac' }),
			mk({ id: 2, file_path: '/m/big/3.flac', track_number: 3 }),
			mk({ id: 3, file_path: '/m/big/1.flac', track_number: 1 }),
			mk({ id: 4, file_path: '/m/big/2.flac', track_number: 2 })
		]);
		expect(groups[0].folder).toBe('/m/big');
		expect(groups[0].files.map((f) => f.track_number)).toEqual([1, 2, 3]);
	});
});
