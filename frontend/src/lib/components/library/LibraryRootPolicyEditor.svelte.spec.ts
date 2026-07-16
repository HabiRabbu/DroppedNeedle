import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

vi.mock('$lib/queries/library/LibraryPolicyQueries.svelte', () => ({
	getLibraryPolicyTreeQuery: () => ({
		data: {
			policy_revision: 'policy-1',
			warnings: [],
			roots: [
				{
					id: 'root-1',
					kind: 'root',
					label: 'Main library',
					path: '/music',
					policy: 'automatic',
					inherited_from_id: 'root-1',
					available: true,
					indexed_file_count: 18,
					on_disk_file_count: 20,
					children: [
						{
							id: 'effective-baroque',
							kind: 'rule',
							label: 'Baroque',
							path: 'Classical/Baroque',
							policy: 'local_metadata',
							inherited_from_id: 'effective-baroque',
							available: true,
							indexed_file_count: 4,
							on_disk_file_count: 5,
							children: []
						}
					]
				}
			]
		}
	})
}));

import LibraryRootPolicyEditor from './LibraryRootPolicyEditor.svelte';

describe('LibraryRootPolicyEditor', () => {
	it('renders backend effective rows with inheritance, availability, and counts', async () => {
		render(LibraryRootPolicyEditor, {
			props: {
				roots: [
					{
						id: 'root-1',
						path: '/music',
						label: 'Main library',
						policy: 'automatic',
						rules: [
							{
								id: 'effective-baroque',
								relative_path: 'Classical/Baroque',
								policy: 'local_metadata'
							}
						]
					}
				],
				onchange: vi.fn()
			}
		} as unknown as Parameters<typeof render>[1]);

		await expect.element(page.getByText('18 indexed · 20 on disk')).toBeVisible();
		await page.getByRole('button', { name: 'Rules' }).click();
		const path = page.getByText('Classical/Baroque');
		await expect.element(path).toBeVisible();
		await expect.element(page.getByText(/Explicit override/)).toBeVisible();
		expect(path.element().parentElement?.textContent).toContain('4');
		expect(path.element().parentElement?.textContent).toContain('indexed');
		await expect
			.element(page.getByLabelText('Policy for Classical/Baroque'))
			.toHaveValue('local_metadata');
	});

	it('hides a saved override as soon as the draft removes it', async () => {
		const root = {
			id: 'root-1',
			path: '/music',
			label: 'Main library',
			policy: 'automatic' as const,
			rules: [
				{
					id: 'effective-baroque',
					relative_path: 'Classical/Baroque',
					policy: 'local_metadata' as const
				}
			]
		};
		const view = render(LibraryRootPolicyEditor, {
			props: { roots: [root], onchange: vi.fn() }
		} as unknown as Parameters<typeof render>[1]);

		await page.getByRole('button', { name: 'Rules' }).click();
		await expect.element(page.getByText('Classical/Baroque')).toBeVisible();
		await view.rerender({ roots: [{ ...root, rules: [] }] });
		await expect.element(page.getByText('Classical/Baroque')).not.toBeInTheDocument();
	});

	it('adds a root through the labelled dialog form', async () => {
		const onchange = vi.fn();
		render(LibraryRootPolicyEditor, {
			props: { roots: [], onchange }
		} as unknown as Parameters<typeof render>[1]);

		await page.getByRole('button', { name: 'Add root' }).click();
		const dialog = page.getByRole('dialog', { name: 'Add library root' });
		await expect.element(dialog.getByRole('heading', { name: 'Add library root' })).toBeVisible();
		await dialog.getByLabelText('Name').fill('Main library');
		await dialog.getByLabelText('Folder path').fill('/music');
		await dialog.getByRole('button', { name: 'Add root', exact: true }).click();

		expect(onchange).toHaveBeenCalledWith([
			{
				id: expect.any(String),
				path: '/music',
				label: 'Main library',
				policy: 'automatic',
				rules: []
			}
		]);
	});
});
