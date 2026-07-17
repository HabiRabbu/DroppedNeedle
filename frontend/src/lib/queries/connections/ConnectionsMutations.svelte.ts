import { api } from '$lib/api/client';
import { createMutation } from '@tanstack/svelte-query';
import { authStore } from '$lib/stores/authStore.svelte';
import { invalidateQueriesWithPersister } from '../QueryClient';
import { ConnectionsQueryKeyFactory } from './ConnectionsQueryKeyFactory';
import { CONNECTIONS_ENDPOINTS } from './endpoints';
import type {
	ConnectionActionResponse,
	LastFmAuthSessionResponse,
	LastFmAuthTokenResponse,
	ListenBrainzConnectVars,
	MediaServerConnectVars,
	PlexLinkPinResponse,
	PlexLinkPollResponse
} from './types';
import type { SourcePlaylistSource } from '$lib/types';
import { SourcePlaylistQueryKeyFactory } from '$lib/queries/source-playlists/SourcePlaylistQueryKeyFactory';

function invalidateConnections(): Promise<void> {
	return invalidateQueriesWithPersister({
		queryKey: ConnectionsQueryKeyFactory.list(authStore.user?.id)
	});
}

function isMediaSource(service: string): service is SourcePlaylistSource {
	return service === 'jellyfin' || service === 'navidrome' || service === 'plex';
}

async function invalidateConnectionAndPlaylists(service?: string): Promise<void> {
	await invalidateConnections();
	if (service && isMediaSource(service)) {
		await invalidateQueriesWithPersister({
			queryKey: SourcePlaylistQueryKeyFactory.source(authStore.user?.id, service)
		});
	}
}

// OAuth step 1: request a desktop token (no state change yet)
export const createLastFmRequestTokenMutation = () =>
	createMutation(() => ({
		mutationFn: () =>
			api.global.post<LastFmAuthTokenResponse>(CONNECTIONS_ENDPOINTS.lastfmAuthToken)
	}));

// OAuth step 2: exchange the approved token for a per-user session
export const createLastFmExchangeSessionMutation = () =>
	createMutation(() => ({
		mutationFn: (token: string) =>
			api.global.post<LastFmAuthSessionResponse>(CONNECTIONS_ENDPOINTS.lastfmAuthSession, {
				token
			}),
		onSuccess: invalidateConnections
	}));

export const createConnectListenBrainzMutation = () =>
	createMutation(() => ({
		mutationFn: (vars: ListenBrainzConnectVars) =>
			api.global.put<ConnectionStatusResponse>(CONNECTIONS_ENDPOINTS.listenbrainz, vars),
		onSuccess: invalidateConnections
	}));

export const createDisconnectMutation = () =>
	createMutation(() => ({
		mutationFn: (service: string) =>
			api.global.delete<ConnectionActionResponse>(CONNECTIONS_ENDPOINTS.connection(service)),
		onSuccess: (_data, service) => invalidateConnectionAndPlaylists(service)
	}));

export const createConnectSpotifyMutation = () =>
	createMutation(() => ({
		mutationFn: async () => {
			const data = await api.global.get<{ auth_url: string }>(CONNECTIONS_ENDPOINTS.spotifyAuthUrl);
			window.location.href = data.auth_url;
		}
	}));

// media-server account links (issue #138): credentials are validated live by the
// backend and never echoed back
export const createConnectNavidromeMutation = () =>
	createMutation(() => ({
		mutationFn: (vars: MediaServerConnectVars) =>
			api.global.put<ConnectionStatusResponse>(CONNECTIONS_ENDPOINTS.navidrome, vars),
		onSuccess: () => invalidateConnectionAndPlaylists('navidrome')
	}));

export const createConnectJellyfinMutation = () =>
	createMutation(() => ({
		mutationFn: (vars: MediaServerConnectVars) =>
			api.global.put<ConnectionStatusResponse>(CONNECTIONS_ENDPOINTS.jellyfin, vars),
		onSuccess: () => invalidateConnectionAndPlaylists('jellyfin')
	}));

// Plex OAuth step 1: mint a pin + popup URL (no state change yet)
export const createPlexLinkPinMutation = () =>
	createMutation(() => ({
		mutationFn: () => api.global.post<PlexLinkPinResponse>(CONNECTIONS_ENDPOINTS.plexAuthPin)
	}));

// Plex OAuth step 2: poll the pin; the backend persists the link on completion
export const createPlexLinkPollMutation = () =>
	createMutation(() => ({
		mutationFn: (pinId: number) =>
			api.global.get<PlexLinkPollResponse>(CONNECTIONS_ENDPOINTS.plexAuthPoll(pinId)),
		onSuccess: (data: PlexLinkPollResponse) =>
			data.completed ? invalidateConnectionAndPlaylists('plex') : Promise.resolve()
	}));

type ConnectionStatusResponse = { service: string; enabled: boolean; username: string };
