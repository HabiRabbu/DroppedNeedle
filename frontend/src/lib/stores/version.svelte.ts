import { PersistedState } from 'runed';

// svelte-ignore state_referenced_locally
const dismissedVersion = new PersistedState<string | null>(
	'droppedneedle_whats_new_dismissed',
	null
);

export function isWhatsNewDismissed(currentVersion: string): boolean {
	return dismissedVersion.current === currentVersion;
}

export function dismissWhatsNew(version: string): void {
	dismissedVersion.current = version;
}
