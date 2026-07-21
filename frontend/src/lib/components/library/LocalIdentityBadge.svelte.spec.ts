import { page } from '@vitest/browser/context';
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import LocalIdentityBadge from './LocalIdentityBadge.svelte';

describe('LocalIdentityBadge.svelte', () => {
	it.each([
		['local_only', 'Local-only'],
		['release_group_linked', 'Local edition'],
		['release_linked', 'MusicBrainz linked']
	] as const)('shows the album identity state %s', async (state, label) => {
		render(LocalIdentityBadge, {
			props: { state, subject: 'album', showDescription: true }
		} as Parameters<typeof render<typeof LocalIdentityBadge>>[1]);

		await expect.element(page.getByText(label, { exact: true })).toBeVisible();
	});

	it('describes artist identity independently', async () => {
		render(LocalIdentityBadge, {
			props: { state: 'musicbrainz_linked', subject: 'artist', showDescription: true }
		} as Parameters<typeof render<typeof LocalIdentityBadge>>[1]);

		await expect.element(page.getByText('This artist is linked to MusicBrainz.')).toBeVisible();
	});
});
