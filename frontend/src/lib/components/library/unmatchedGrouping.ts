import type { ManualReviewEntry } from '$lib/types';

export interface UnmatchedGroup {
	folder: string;
	folderName: string;
	files: ManualReviewEntry[];
	guessedAlbum: string | null;
	guessedArtist: string | null;
}

function parentFolder(path: string): string {
	const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
	return i > 0 ? path.slice(0, i) : path;
}

function basename(path: string): string {
	const trimmed = path.replace(/[/\\]+$/, '');
	const i = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
	return i >= 0 ? trimmed.slice(i + 1) : trimmed;
}

/** Most common non-empty value (ties broken by first seen). */
function mode(values: (string | null)[]): string | null {
	const counts = new Map<string, number>();
	for (const v of values) {
		if (!v) continue;
		counts.set(v, (counts.get(v) ?? 0) + 1);
	}
	let best: string | null = null;
	let bestN = 0;
	for (const [v, n] of counts) {
		if (n > bestN) {
			best = v;
			bestN = n;
		}
	}
	return best;
}

export function groupUnmatched(items: ManualReviewEntry[]): UnmatchedGroup[] {
	const byFolder = new Map<string, ManualReviewEntry[]>();
	for (const item of items) {
		const folder = parentFolder(item.file_path);
		const arr = byFolder.get(folder);
		if (arr) arr.push(item);
		else byFolder.set(folder, [item]);
	}

	const groups: UnmatchedGroup[] = [];
	for (const [folder, files] of byFolder) {
		const sorted = [...files].sort((a, b) => (a.track_number ?? 9999) - (b.track_number ?? 9999));
		groups.push({
			folder,
			folderName: basename(folder),
			files: sorted,
			guessedAlbum: mode(files.map((f) => f.extracted_album)),
			guessedArtist: mode(files.map((f) => f.extracted_artist))
		});
	}
	groups.sort((a, b) => b.files.length - a.files.length);
	return groups;
}
