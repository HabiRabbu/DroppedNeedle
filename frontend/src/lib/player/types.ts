export type PlaybackState =
	| 'idle'
	| 'loading'
	| 'playing'
	| 'paused'
	| 'ended'
	| 'buffering'
	| 'error';

export type SourceType = 'youtube' | 'local' | 'jellyfin' | 'navidrome' | 'plex';

export type QueueOrigin = 'context' | 'manual';

export interface PlaybackSource {
	readonly type: SourceType;

	load(info: {
		trackSourceId?: string;
		url?: string;
		token?: string;
		format?: string;
		duration?: number;
	}): Promise<void>;
	play(): void;
	pause(): void;
	seekTo(seconds: number): void;
	setVolume(level: number): void;
	getCurrentTime(): number;
	getDuration(): number;
	isSeekable?(): boolean;
	destroy(): void;

	onStateChange(callback: (state: PlaybackState) => void): void;
	onReady(callback: () => void): void;
	onError(callback: (error: { code: string; message: string }) => void): void;
	onProgress(callback: (currentTime: number, duration: number) => void): void;
}

export interface NowPlaying {
	albumId: string;
	albumName: string;
	artistName: string;
	coverUrl: string | null;
	/** Raw remote cover URL (pre-proxy) so large displays reuse the browser-cached carousel image instead of cold-fetching covers. */
	coverRemoteUrl?: string | null;
	sourceType: SourceType;
	discNumber?: number;
	trackSourceId?: string;
	embedUrl?: string;
	trackName?: string;
	artistId?: string;
	streamUrl?: string;
	format?: string;
	playlistTrackId?: string;
	/** 30s preview stream (radio preview tier): never scrobbled/reported, fades out. */
	isPreview?: boolean;
}

export type PlaybackMeta = {
	albumId: string;
	albumName: string;
	artistName: string;
	coverUrl: string | null;
	artistId?: string;
};

export interface QueueItem {
	/** Source-specific item identifier (Jellyfin item ID, local file ID, or YouTube video ID). */
	trackSourceId: string;
	trackName: string;
	artistName: string;
	trackNumber: number;
	discNumber?: number;
	albumId: string;
	albumName: string;
	coverUrl: string | null;
	/** Raw remote cover URL (pre-proxy) so large displays reuse the browser-cached carousel image instead of cold-fetching covers. */
	coverRemoteUrl?: string | null;
	sourceType: SourceType;
	artistId?: string;
	streamUrl?: string;
	format?: string;
	availableSources?: SourceType[];
	sourceIds?: Partial<Record<SourceType, string>>;
	duration?: number;
	playSessionId?: string;
	/** Plex ratingKey used for scrobble and now-playing calls. Streaming uses part_key in trackSourceId. */
	plexRatingKey?: string;
	queueOrigin?: QueueOrigin;
	/** Stable playlist-level track identifier that survives source changes. */
	playlistTrackId?: string;
	/** 30s preview stream (radio preview tier): never scrobbled/reported, fades out. */
	isPreview?: boolean;
}
