/** Mirrors the backend `ProfileResponse` (api/v1/schemas/profile.py). `providers`
 *  is the authoritative list used to choose change- vs set-password (D8). */
export interface ProfileServiceConnection {
	name: string;
	enabled: boolean;
	username: string;
	url: string;
}

export interface ProfileLibraryStats {
	source: string;
	total_tracks: number;
	total_albums: number;
	total_artists: number;
	total_size_bytes: number;
	total_size_human: string;
}

export interface ProfileData {
	display_name: string;
	avatar_url: string;
	username: string | null;
	username_display: string | null;
	email: string | null;
	providers: string[];
	services: ProfileServiceConnection[];
	library_stats: ProfileLibraryStats[];
}

export interface DisplayNameUpdateVars {
	display_name: string;
}

export interface UsernameUpdateVars {
	username: string;
}

export interface EmailUpdateVars {
	email: string | null;
}

export interface ChangePasswordVars {
	current_password: string;
	new_password: string;
}

export interface SetPasswordVars {
	new_password: string;
}
