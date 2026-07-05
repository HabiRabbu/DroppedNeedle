// mirrors backend api/v1/schemas/artist.py (FollowStatusResponse) and the
// following hub responses
export type AutoDownloadState = 'none' | 'pending' | 'approved' | 'rejected' | 'revoked';

export interface FollowStatus {
	followed: boolean;
	auto_download: boolean;
	auto_download_state: AutoDownloadState;
}

export interface FollowedArtist {
	mbid: string;
	name: string;
	image_url?: string | null;
	auto_download: boolean;
	auto_download_state: AutoDownloadState;
	followed_at: number;
}

export interface NewRelease {
	release_group_mbid: string;
	title: string;
	artist_name: string;
	artist_mbid: string;
	primary_type?: string | null;
	first_release_date?: string | null;
}

export interface NewReleasesResponse {
	items: NewRelease[];
	total: number;
}

// mirrors backend api/v1/schemas/following.py (UnseenCountResponse)
export interface UnseenCountResponse {
	count: number;
}

export interface AutoDownloadApproval {
	user_id: string;
	artist_mbid: string;
	artist_name: string;
	requested_at: number;
	user_name?: string | null;
}

export interface AutoDownloadApprovalsResponse {
	items: AutoDownloadApproval[];
	count: number;
}

export interface ApprovalActionResponse {
	success: boolean;
	message: string;
}
