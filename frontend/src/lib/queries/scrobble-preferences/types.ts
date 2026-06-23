import type { MusicSource } from '$lib/stores/musicSource';

// mirrors the backend /api/v1/me/scrobble-preferences DTOs
export interface ScrobblePreferences {
	scrobble_to_lastfm: boolean;
	scrobble_to_listenbrainz: boolean;
	primary_music_source: string;
}

export interface ScrobblePreferencesUpdate {
	scrobble_to_lastfm?: boolean;
	scrobble_to_listenbrainz?: boolean;
	primary_music_source?: MusicSource;
}
