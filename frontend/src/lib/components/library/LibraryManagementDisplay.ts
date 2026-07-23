import type {
	DuplicateCollisionKind,
	LibraryManagementPlanItem
} from '$lib/queries/library-management/types';

export interface ManagementFieldDiff {
	name: string;
	operation: string;
	before: unknown;
	after: unknown;
	representationLoss: string | null;
}

export interface ManagementCollision {
	classification: string;
	requestKind: DuplicateCollisionKind | null;
	existingRootId: string | null;
	existingRelativePath: string | null;
	existingLocalTrackId: string | null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringOrNull(value: unknown): string | null {
	return typeof value === 'string' && value.length > 0 ? value : null;
}

export function managementFieldDiffs(item: LibraryManagementPlanItem): ManagementFieldDiff[] {
	const raw = item.diff.field_mutations;
	if (!Array.isArray(raw)) return [];
	return raw.flatMap((value) => {
		if (!isRecord(value) || typeof value.name !== 'string' || typeof value.operation !== 'string') {
			return [];
		}
		return [
			{
				name: value.name,
				operation: value.operation,
				before: value.before,
				after: value.after,
				representationLoss: stringOrNull(value.representation_loss)
			}
		];
	});
}

export function managementCustomTagDiffs(item: LibraryManagementPlanItem): ManagementFieldDiff[] {
	const raw = item.diff.custom_tag_mutations;
	if (!Array.isArray(raw)) return [];
	return raw.flatMap((value) => {
		if (!isRecord(value) || typeof value.name !== 'string' || typeof value.operation !== 'string') {
			return [];
		}
		return [
			{
				name: `Custom: ${value.name}`,
				operation: value.operation,
				before: value.before,
				after: value.after,
				representationLoss: null
			}
		];
	});
}

export function managementStringList(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === 'string')
		: [];
}

export function managementAudioFormat(item: LibraryManagementPlanItem): string {
	return stringOrNull(item.capability.audio_format) ?? 'unknown';
}

export function managementAdapter(item: LibraryManagementPlanItem): string | null {
	return stringOrNull(item.capability.adapter);
}

export function managementSidecars(
	item: LibraryManagementPlanItem
): Array<Record<string, unknown>> {
	const value = item.diff.sidecars;
	return Array.isArray(value) ? value.filter(isRecord) : [];
}

function collisionRequestKind(classification: string): DuplicateCollisionKind | null {
	const exact: DuplicateCollisionKind[] = [
		'same_path_same_content',
		'same_path_different_content',
		'same_release_position_different_content',
		'normalized_path_collision',
		'sidecar_collision',
		'destination_created_after_preview'
	];
	if (exact.includes(classification as DuplicateCollisionKind)) {
		return classification as DuplicateCollisionKind;
	}
	if (classification === 'normalized_catalog_path_collision') return 'normalized_path_collision';
	if (classification === 'sidecar_path_collision') return 'sidecar_collision';
	return null;
}

export function managementCollisions(item: LibraryManagementPlanItem): ManagementCollision[] {
	return item.collisions.flatMap((value) => {
		if (!isRecord(value) || typeof value.classification !== 'string') return [];
		return [
			{
				classification: value.classification,
				requestKind: collisionRequestKind(value.classification),
				existingRootId:
					stringOrNull(value.existing_root_id) ??
					stringOrNull(value.destination_root_id) ??
					item.destination_root_id,
				existingRelativePath:
					stringOrNull(value.existing_relative_path) ??
					stringOrNull(value.destination_relative_path) ??
					item.destination_relative_path,
				existingLocalTrackId:
					stringOrNull(value.existing_local_track_id) ?? stringOrNull(value.catalog_track_id)
			}
		];
	});
}

export function formatManagementValue(value: unknown): string {
	if (value === null || value === undefined || value === '') return 'Empty';
	if (Array.isArray(value))
		return value.length ? value.map(formatManagementValue).join(' · ') : 'Empty';
	if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
		return String(value);
	}
	if (isRecord(value)) {
		return Object.entries(value)
			.map(([key, item]) => `${titleManagementValue(key)}: ${formatManagementValue(item)}`)
			.join(' · ');
	}
	return 'Unavailable';
}

export function titleManagementValue(value: string): string {
	return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
