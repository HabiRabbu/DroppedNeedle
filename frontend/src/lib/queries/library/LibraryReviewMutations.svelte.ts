import { createMutation } from '@tanstack/svelte-query';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { toastStore } from '$lib/stores/toast';
import { searchStore } from '$lib/stores/search';
import { ArtistQueryKeyFactory } from '$lib/queries/artist/ArtistQueryKeyFactory';
import { DiscoverQueryKeyFactory } from '$lib/queries/discover/DiscoverQueryKeyFactory';
import { HomeQueryKeyFactory } from '$lib/queries/HomeQueryKeyFactory';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type {
	BulkReviewAction,
	BulkReviewPreviewResponse,
	BulkReviewSelection,
	CandidateAcceptanceRequest,
	OperationResponse,
	ReviewActionRequest,
	ReviewActionResponse
} from './LibraryOperationsTypes';

async function invalidateReviewState(reviewId?: string): Promise<void> {
	searchStore.clear();
	await Promise.all([
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.reviewsPrefix() }),
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.activityPrefix() }),
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.operationsPrefix() }),
		...(reviewId
			? [invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.review(reviewId) })]
			: []),
		invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.all }),
		invalidateQueriesWithPersister({ queryKey: ArtistQueryKeyFactory.prefix }),
		invalidateQueriesWithPersister({ queryKey: HomeQueryKeyFactory.prefix }),
		invalidateQueriesWithPersister({ queryKey: DiscoverQueryKeyFactory.prefix })
	]);
}

export type ReviewAction = 'keep_tagged' | 'detach_keep_tagged' | 'exclude' | 'restore';

export function actOnLibraryReview(action: ReviewAction) {
	return createMutation(() => ({
		mutationFn: (input: { reviewId: string; body: ReviewActionRequest }) => {
			const url =
				action === 'keep_tagged'
					? API.library.reviewKeepTagged(input.reviewId)
					: action === 'detach_keep_tagged'
						? API.library.reviewDetachKeepTagged(input.reviewId)
						: action === 'exclude'
							? API.library.reviewExclude(input.reviewId)
							: API.library.reviewRestore(input.reviewId);
			return api.global.post<ReviewActionResponse>(url, input.body);
		},
		onSuccess: async (_result, input) => {
			await invalidateReviewState(input.reviewId);
			toastStore.show({ message: 'Review decision saved', type: 'success' });
		},
		onError: () => toastStore.show({ message: 'Could not save the review decision', type: 'error' })
	}));
}

export function acceptLibraryReviewCandidate() {
	return createMutation(() => ({
		mutationFn: (input: { reviewId: string; body: CandidateAcceptanceRequest }) =>
			api.global.post<ReviewActionResponse>(
				API.library.reviewCandidate(input.reviewId),
				input.body
			),
		onSuccess: async (_result, input) => {
			await invalidateReviewState(input.reviewId);
			toastStore.show({ message: 'Release selected', type: 'success' });
		},
		onError: () => toastStore.show({ message: 'Could not select this release', type: 'error' })
	}));
}

export function retryLibraryReview() {
	return createMutation(() => ({
		mutationFn: (input: { reviewId: string; body: ReviewActionRequest }) =>
			api.global.post<OperationResponse>(API.library.reviewRetry(input.reviewId), input.body),
		onSuccess: async (_result, input) => {
			await invalidateReviewState(input.reviewId);
			toastStore.show({ message: 'Identification retry started', type: 'success' });
		},
		onError: () => toastStore.show({ message: 'Could not retry identification', type: 'error' })
	}));
}

export function previewBulkLibraryReview() {
	return createMutation(() => ({
		mutationFn: (input: {
			action: BulkReviewAction;
			selection: BulkReviewSelection;
			candidate_key?: string | null;
		}) => api.global.post<BulkReviewPreviewResponse>(API.library.bulkReviewPreview(), input)
	}));
}

export function applyBulkLibraryReview() {
	return createMutation(() => ({
		mutationFn: (input: {
			preview_token: string;
			idempotency_key: string;
			action: BulkReviewAction;
			selection: BulkReviewSelection;
			candidate_key?: string | null;
			confirm_local_metadata?: boolean;
		}) => api.global.post<OperationResponse>(API.library.bulkReviewApply(), input),
		onSuccess: async () => {
			await invalidateReviewState();
			toastStore.show({ message: 'Bulk review started', type: 'success' });
		},
		onError: () => toastStore.show({ message: 'Could not start the bulk review', type: 'error' })
	}));
}
