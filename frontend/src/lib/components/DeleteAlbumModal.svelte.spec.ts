import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const mutateAsync = vi.fn();

vi.mock('$lib/queries/library/LibraryMutations.svelte', () => ({
	removeLibraryAlbum: () => ({ mutateAsync, isPending: false })
}));

import DeleteAlbumModal from './DeleteAlbumModal.svelte';

function renderModal(ondeleted = vi.fn(), onclose = vi.fn()) {
	return {
		ondeleted,
		onclose,
		...render(DeleteAlbumModal, {
			props: {
				albumTitle: 'Blue Lines',
				artistName: 'Massive Attack',
				musicbrainzId: 'rg-1',
				ondeleted,
				onclose
			}
		} as unknown as Parameters<typeof render<typeof DeleteAlbumModal>>[1])
	};
}

describe('DeleteAlbumModal', () => {
	beforeEach(() => {
		mutateAsync.mockReset();
		mutateAsync.mockResolvedValue({ success: true });
	});

	it('describes only the selected album file deletion', async () => {
		renderModal();

		await expect.element(page.getByRole('heading', { name: 'Remove Album' })).toBeVisible();
		await expect.element(page.getByText(/Blue Lines/)).toBeVisible();
		await expect.element(page.getByText(/permanently deleted from disk/)).toBeVisible();
		await expect.element(page.getByText(/also remove/i)).not.toBeInTheDocument();
		await expect.element(page.getByText(/Checking artist impact/i)).not.toBeInTheDocument();
	});

	it('waits for removal before reporting success', async () => {
		const { ondeleted } = renderModal();

		await page.getByRole('button', { name: 'Remove' }).click();

		expect(mutateAsync).toHaveBeenCalledWith('rg-1');
		await vi.waitFor(() => expect(ondeleted).toHaveBeenCalledOnce());
	});

	it('keeps the confirmation open when removal fails', async () => {
		mutateAsync.mockRejectedValueOnce(new Error("Couldn't remove this album"));
		const { ondeleted } = renderModal();

		await page.getByRole('button', { name: 'Remove' }).click();

		await expect.element(page.getByText("Couldn't remove this album")).toBeVisible();
		await expect.element(page.getByRole('heading', { name: 'Remove Album' })).toBeVisible();
		expect(ondeleted).not.toHaveBeenCalled();
	});
});
