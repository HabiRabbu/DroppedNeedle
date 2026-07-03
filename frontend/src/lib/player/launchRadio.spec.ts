import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RadioPlanTrack } from '$lib/types';

const { apiMock, playerMock, toastMock } = vi.hoisted(() => ({
	apiMock: { global: { get: vi.fn(), post: vi.fn() } },
	playerMock: {
		queue: [] as unknown[],
		currentIndex: 0,
		isPlaying: false,
		playQueue: vi.fn(),
		addMultipleToQueue: vi.fn(),
		patchQueueItemByPlaylistTrackId: vi.fn(),
		removeFromQueue: vi.fn(),
		pause: vi.fn()
	},
	toastMock: { show: vi.fn() }
}));

vi.mock('$lib/api/client', () => ({ api: apiMock }));
vi.mock('$lib/stores/player.svelte', () => ({ playerStore: playerMock }));
vi.mock('$lib/stores/playbackToast.svelte', () => ({ playbackToast: toastMock }));
const resolveRadioPatch = vi.hoisted(() => vi.fn());
vi.mock('$lib/player/radioQueueHydrator', () => ({
	startRadioHydration: vi.fn(),
	stopRadioHydration: vi.fn(),
	prepareRadioHydration: vi.fn(),
	resolveRadioPatch: (...args: unknown[]) => resolveRadioPatch(...args),
	needsHydration: (item: {
		sourceType: string;
		trackSourceId?: string;
		playlistTrackId?: string;
	}) => {
		if (!item.playlistTrackId?.startsWith('radio:')) return false;
		return item.sourceType === 'youtube' && !item.trackSourceId;
	}
}));

import { launchRadio, planTrackToQueueItem } from './launchRadio';
import { radioSession } from '$lib/stores/radioSession.svelte';

function track(overrides: Partial<RadioPlanTrack> = {}): RadioPlanTrack {
	return {
		track_name: 'Song',
		artist_name: 'Artist',
		artist_mbid: 'a-1',
		recording_mbid: 'rec-1',
		album_mbid: 'rg-1',
		album_name: 'Album',
		in_library: false,
		local_file_id: null,
		file_format: null,
		duration_s: null,
		...overrides
	};
}

describe('planTrackToQueueItem tiers', () => {
	it('library tracks stream natively via the local file', () => {
		const item = planTrackToQueueItem(
			track({ in_library: true, local_file_id: 'file-9', file_format: 'flac' }),
			true
		);
		expect(item).not.toBeNull();
		expect(item!.sourceType).toBe('local');
		expect(item!.trackSourceId).toBe('file-9');
	});

	it('un-owned tracks become YouTube placeholders when configured', () => {
		const item = planTrackToQueueItem(track(), true);
		expect(item).not.toBeNull();
		expect(item!.sourceType).toBe('youtube');
		expect(item!.trackSourceId).toBe('');
		expect(item!.playlistTrackId).toContain('radio:');
	});

	it('un-owned tracks without YouTube are dropped (previews are not a player tier)', () => {
		// previews are cross-origin clips the player's Web Audio graph mutes; they
		// live in the floating widget, so the player queue simply omits these
		const item = planTrackToQueueItem(track(), false);
		expect(item).toBeNull();
	});
});

describe('launchRadio', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		resolveRadioPatch.mockResolvedValue({ trackSourceId: 'vid-default' });
		radioSession.end();
	});

	it('resolves the first YouTube placeholder BEFORE playback starts', async () => {
		apiMock.global.post.mockResolvedValue({ title: 'Radio', tracks: [track()] });
		resolveRadioPatch.mockResolvedValue({ trackSourceId: 'vid-1' });

		const ok = await launchRadio({ seed_type: 'genre', seed_id: 'x' }, true);

		expect(ok).toBe(true);
		expect(resolveRadioPatch).toHaveBeenCalledTimes(1);
		const [items] = playerMock.playQueue.mock.calls[0];
		// the head is playable at playQueue time - no startup error cascade
		expect(items[0].trackSourceId).toBe('vid-1');
	});

	it('drops dead heads and aborts when nothing resolves', async () => {
		apiMock.global.post.mockResolvedValue({ title: 'Radio', tracks: [track()] });
		resolveRadioPatch.mockResolvedValue(null);

		const ok = await launchRadio({ seed_type: 'genre', seed_id: 'x' }, true);

		expect(ok).toBe(false);
		expect(playerMock.playQueue).not.toHaveBeenCalled();
		expect(radioSession.active).toBe(false);
	});

	it('starts playback from the fast plan and starts a session', async () => {
		apiMock.global.post.mockResolvedValue({
			title: 'Radio: Shoegaze',
			tracks: [track(), track({ track_name: 'Other', recording_mbid: 'rec-2' })]
		});

		const ok = await launchRadio({ seed_type: 'genre', seed_id: 'shoegaze' }, true);

		expect(ok).toBe(true);
		expect(radioSession.active).toBe(true);
		expect(radioSession.title).toBe('Radio: Shoegaze');
		expect(playerMock.playQueue).toHaveBeenCalledTimes(1);
		const [items] = playerMock.playQueue.mock.calls[0];
		expect(items).toHaveLength(2);
		// fast first call, then the background full-plan extension
		expect(apiMock.global.post.mock.calls[0][1]).toMatchObject({ fast: true });
	});

	it('empty plan warns instead of playing', async () => {
		apiMock.global.post.mockResolvedValue({ title: 'Radio', tracks: [] });

		const ok = await launchRadio({ seed_type: 'artist', seed_id: 'a-1', mode: 'library' }, false);

		expect(ok).toBe(false);
		expect(playerMock.playQueue).not.toHaveBeenCalled();
		expect(toastMock.show).toHaveBeenCalled();
	});

	it('un-owned tracks without YouTube are dropped from the station', async () => {
		// a station of only un-owned tracks + no YouTube has nothing for the player
		apiMock.global.post.mockResolvedValue({ title: 'Radio', tracks: [track()] });

		const ok = await launchRadio({ seed_type: 'genre', seed_id: 'x' }, false);

		expect(ok).toBe(false);
		expect(playerMock.playQueue).not.toHaveBeenCalled();
	});

	it('session dedupes tracks across extensions', async () => {
		apiMock.global.post.mockResolvedValue({
			title: 'Radio',
			tracks: [track(), track()] // duplicate in one plan
		});

		await launchRadio({ seed_type: 'artist', seed_id: 'a-1' }, true);

		const [items] = playerMock.playQueue.mock.calls[0];
		expect(items).toHaveLength(1);
	});
});
