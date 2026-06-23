// mirrors backend api/v1/schemas/me_connections.py; the encrypted secret
// (token/session_key) is never sent to the client (AMU-3/AMU-6)
export interface ConnectionStatus {
	service: string;
	enabled: boolean;
	username: string;
}

export interface ConnectionsResponse {
	connections: ConnectionStatus[];
}

export interface ConnectionActionResponse {
	service: string;
	deleted: boolean;
}

export interface LastFmAuthTokenResponse {
	token: string;
	auth_url: string;
}

export interface LastFmAuthSessionResponse {
	success: boolean;
	message: string;
	username: string;
}

export interface ListenBrainzConnectVars {
	user_token: string;
	username: string;
}
