import { describe, expect, it } from 'vitest';
import type { ManualReviewEntry, Track } from '$lib/types';
import { pairScore, suggestAssignments } from './unmatchedMatching';

function file(partial: Partial<ManualReviewEntry> & { id: number }): ManualReviewEntry {
	return {
		file_path: `/m/${partial.id}.flac`,
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

function track(
	position: number,
	title: string,
	length: number | null = null,
	recording_id = `rec-${position}`
): Track {
	return { position, title, length, recording_id, disc_number: 1 };
}

describe('pairScore', () => {
	it('rewards an exact track-number match', () => {
		expect(
			pairScore(file({ id: 1, track_number: 3 }), track(3, 'Whatever'))
		).toBeGreaterThanOrEqual(100);
	});

	it('rewards an exact title match', () => {
		expect(
			pairScore(file({ id: 1, extracted_title: 'Airbag' }), track(1, 'Airbag'))
		).toBeGreaterThanOrEqual(60);
	});

	it('rewards a close duration', () => {
		const exact = pairScore(file({ id: 1, duration: 284 }), track(1, 'x', 284000));
		const off = pairScore(file({ id: 1, duration: 100 }), track(1, 'x', 284000));
		expect(exact).toBeGreaterThan(off);
	});

	it('gives zero when there is no signal', () => {
		expect(pairScore(file({ id: 1 }), track(1, 'x'))).toBe(0);
	});
});

describe('suggestAssignments', () => {
	it('places files onto their matching track slots, each slot once', () => {
		const files = [
			file({ id: 10, track_number: 2, extracted_title: 'Paranoid Android' }),
			file({ id: 11, track_number: 1, extracted_title: 'Airbag' })
		];
		const tracks = [track(1, 'Airbag'), track(2, 'Paranoid Android')];
		const assigned = suggestAssignments(files, tracks);
		expect(assigned).toEqual({ 11: 0, 10: 1 });
	});

	it('does not assign files with no usable signal', () => {
		const files = [file({ id: 1 })];
		const tracks = [track(1, 'Airbag')];
		expect(suggestAssignments(files, tracks)).toEqual({});
	});

	it('never double-books a track when two files contend', () => {
		const files = [
			file({ id: 1, extracted_title: 'Airbag', track_number: 1 }),
			file({ id: 2, extracted_title: 'Airbag' })
		];
		const tracks = [track(1, 'Airbag')];
		const assigned = suggestAssignments(files, tracks);
		const slots = Object.values(assigned);
		const unique = slots.filter((v, i) => slots.indexOf(v) === i);
		expect(unique.length).toBe(slots.length);
		expect(assigned[1]).toBe(0);
	});
});
