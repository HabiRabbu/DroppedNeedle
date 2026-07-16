import { API } from '$lib/constants';
import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';

export function createLibraryActivityEvents() {
	let activitySource: EventSource | null = null;
	let operationsSource: EventSource | null = null;

	function invalidateActivity(): void {
		void invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.activityPrefix() });
	}

	function invalidateOperations(): void {
		void invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.operationsPrefix() });
		void invalidateQueriesWithPersister({ queryKey: LibraryQueryKeyFactory.reviewsPrefix() });
		invalidateActivity();
	}

	function start(admin: boolean): void {
		stop();
		activitySource = new EventSource(API.library.activityStream());
		activitySource.addEventListener('open', invalidateActivity);
		activitySource.addEventListener('activity.changed', invalidateActivity);
		if (admin) {
			operationsSource = new EventSource(API.library.operationsStream());
			operationsSource.addEventListener('open', invalidateOperations);
			operationsSource.addEventListener('activity.changed', invalidateOperations);
		}
	}

	function stop(): void {
		activitySource?.close();
		operationsSource?.close();
		activitySource = null;
		operationsSource = null;
	}

	return { start, stop };
}
