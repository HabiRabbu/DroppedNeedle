import type { ManualReviewEntry, Track } from '$lib/types';

const SUGGEST_THRESHOLD = 50;

function norm(s: string | null | undefined): string {
	return (s ?? '')
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, ' ')
		.trim();
}

/** How well one file fits one track. */
export function pairScore(file: ManualReviewEntry, track: Track): number {
	let score = 0;
	if (file.track_number && track.position && file.track_number === track.position) score += 100;

	const ft = norm(file.extracted_title);
	const tt = norm(track.title);
	if (ft && tt) {
		if (ft === tt) score += 60;
		else if (ft.includes(tt) || tt.includes(ft)) score += 35;
		else {
			const aTokens = ft.split(' ');
			const b = tt.split(' ');
			const overlap = b.filter((w) => aTokens.includes(w)).length;
			if (b.length) score += Math.round((overlap / b.length) * 30);
		}
	}

	if (file.duration && track.length) {
		const diff = Math.abs(file.duration - track.length / 1000) / (track.length / 1000);
		if (diff <= 0.05) score += 20;
		else if (diff <= 0.15) score += 10;
	}
	return score;
}

/** Greedily map files to track slot indices by best score, each used at most once. */
export function suggestAssignments(
	files: ManualReviewEntry[],
	tracks: Track[]
): Record<number, number> {
	const pairs: { fileId: number; slot: number; score: number }[] = [];
	files.forEach((f) => {
		tracks.forEach((t, i) => {
			const score = pairScore(f, t);
			if (score >= SUGGEST_THRESHOLD) pairs.push({ fileId: f.id, slot: i, score });
		});
	});
	pairs.sort((a, b) => b.score - a.score);

	const assigned: Record<number, number> = {};
	const usedSlots: Record<number, boolean> = {};
	for (const p of pairs) {
		if (assigned[p.fileId] !== undefined || usedSlots[p.slot]) continue;
		assigned[p.fileId] = p.slot;
		usedSlots[p.slot] = true;
	}
	return assigned;
}
