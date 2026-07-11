import { page } from '@vitest/browser/context';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-svelte';
import type { DiscoverResponse } from '$lib/types';

vi.mock('$env/dynamic/public', () => ({
	env: { PUBLIC_API_URL: '' }
}));

const { discoverState, deckState } = vi.hoisted(() => ({
	discoverState: {
		data: undefined as Partial<DiscoverResponse> | undefined,
		isLoading: false,
		isFetching: false,
		isRefetching: false,
		error: null as Error | null,
		dataUpdatedAt: 0,
		refetch: () => {}
	},
	deckState: { shouldThrow: false }
}));

vi.mock('$lib/queries/discover/DiscoverQuery.svelte', () => ({
	getDiscoverQuery: () => discoverState,
	getDiscoverQueryOptions: () => ({ queryKey: ['discover'], queryFn: () => ({}) }),
	getRadioQuery: () => ({ data: undefined, isLoading: false }),
	getPlaylistSuggestionsQuery: () => ({ data: undefined, isLoading: false })
}));
vi.mock('$lib/queries/section-prefs/SectionPrefsQuery.svelte', () => ({
	getSectionPrefsQuery: () => ({ data: undefined, isLoading: false })
}));
vi.mock('$lib/queries/QueryClient', () => ({
	invalidateQueriesWithPersister: vi.fn().mockResolvedValue(undefined),
	setQueryDataWithPersister: vi.fn().mockResolvedValue(undefined)
}));
vi.mock('$lib/api/client', () => {
	class ApiError extends Error {}
	class SessionExpiredError extends ApiError {}
	return {
		ApiError,
		SessionExpiredError,
		api: { global: { get: vi.fn(), post: vi.fn().mockResolvedValue({}) } }
	};
});
vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { user: { id: 'u1' }, isAdmin: false }
}));
// the deck fetches its own queue; stub it, optionally throwing to exercise the boundary
vi.mock('$lib/components/discover/DiscoverQueueDeck.svelte', () => ({
	default: function () {
		if (deckState.shouldThrow) throw new Error('deck exploded');
	}
}));
vi.mock('$lib/components/PlaylistDiscoveryModal.svelte', () => {
	const Comp = function () {};
	Comp.prototype = {};
	return { default: Comp };
});

import DiscoverPage from './+page.svelte';

function emptyResponse(overrides: Partial<DiscoverResponse> = {}): Partial<DiscoverResponse> {
	return {
		because_you_listen_to: [],
		discover_queue_enabled: false,
		service_prompts: [],
		daily_mixes: [],
		radio_sections: [],
		refreshing: false,
		service_status: null,
		...overrides
	};
}

describe('/discover degraded and error states (#147)', () => {
	beforeEach(() => {
		discoverState.data = undefined;
		discoverState.isLoading = false;
		discoverState.isFetching = false;
		discoverState.isRefetching = false;
		deckState.shouldThrow = false;
	});

	it('shows a terminal degraded state instead of endless skeletons', async () => {
		discoverState.data = emptyResponse({
			service_status: { listenbrainz: 'degraded' }
		});
		render(DiscoverPage);

		await expect
			.element(page.getByRole('heading', { name: 'Recommendations Unavailable' }))
			.toBeVisible();
		await expect.element(page.getByText(/Listenbrainz\s+is temporarily unavailable/)).toBeVisible();
		await expect.element(page.getByRole('button', { name: /Retry Now/ })).toBeVisible();
	});

	it('explains a slow build while sources are degraded', async () => {
		discoverState.data = emptyResponse({
			refreshing: true,
			service_status: { listenbrainz: 'degraded' }
		});
		render(DiscoverPage);

		await expect.element(page.getByText(/Building your recommendations/)).toBeVisible();
		await expect.element(page.getByText(/so this may take longer than usual/)).toBeVisible();
	});

	it('falls back to the generic empty state when nothing is degraded', async () => {
		discoverState.data = emptyResponse({ discover_queue_enabled: true });
		render(DiscoverPage);

		await expect.element(page.getByRole('heading', { name: 'Still Loading' })).toBeVisible();
	});

	it('a crashing section degrades to an inline error card instead of killing the page', async () => {
		deckState.shouldThrow = true;
		discoverState.data = emptyResponse({ discover_queue_enabled: true });
		render(DiscoverPage);

		await expect.element(page.getByText('Something Went Wrong')).toBeVisible();
		await expect.element(page.getByRole('button', { name: 'Try Again' })).toBeVisible();
	});

	it('renders content normally when nothing crashes', async () => {
		discoverState.data = emptyResponse({
			discover_queue_enabled: true,
			globally_trending: {
				title: 'Globally Trending',
				type: 'artists',
				items: [],
				source: null,
				fallback_message: null,
				connect_service: null
			}
		});
		render(DiscoverPage);

		await expect.element(page.getByText('Because You Listened')).toBeVisible();
		await expect.element(page.getByText('Something Went Wrong')).not.toBeInTheDocument();
	});
});
