import { page } from '@vitest/browser/context';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import type { ScoredCandidate } from '$lib/types';

import SearchResultCard from './SearchResultCard.svelte';

type RenderOpts = Parameters<typeof render<typeof SearchResultCard>>[1];

function renderCard(props: Record<string, unknown>) {
	return render(SearchResultCard, { props } as unknown as RenderOpts);
}

function makeCandidate(overrides: Partial<ScoredCandidate> = {}): ScoredCandidate {
	return {
		username: 'alice',
		parent_directory: 'Radiohead - OK Computer (1997)',
		files: [
			{
				username: 'alice',
				filename: 'Radiohead/OK Computer/01 Airbag.flac',
				parent_directory: 'Radiohead - OK Computer (1997)',
				size: 30_000_000,
				extension: 'flac',
				bitrate: null,
				bit_depth: 16,
				sample_rate: 44100,
				duration: 284,
				has_free_slot: true,
				upload_speed: 2_000_000
			}
		],
		coherence: 0.95,
		file_confidence: 0.9,
		final_score: 0.88,
		tier: 'manual',
		...overrides
	};
}

describe('SearchResultCard.svelte', () => {
	it('renders folder, peer, score percentage and format', async () => {
		renderCard({ candidate: makeCandidate() });
		await expect.element(page.getByText('Radiohead - OK Computer (1997)')).toBeInTheDocument();
		await expect.element(page.getByText('alice')).toBeInTheDocument();
		await expect.element(page.getByText('88%')).toBeInTheDocument();
		await expect.element(page.getByText('FLAC')).toBeInTheDocument();
	});

	it('calls onPick when Pick is clicked', async () => {
		const onPick = vi.fn();
		renderCard({ candidate: makeCandidate(), onPick });
		await page.getByRole('button', { name: /Pick candidate from alice/ }).click();
		expect(onPick).toHaveBeenCalledOnce();
	});

	it('exposes the score breakdown via a tooltip', async () => {
		renderCard({ candidate: makeCandidate() });
		await expect.element(page.getByText('88%')).toBeInTheDocument();
		const tip = document.querySelector('[data-tip]');
		expect(tip?.getAttribute('data-tip')).toContain('Coherence');
	});
});
