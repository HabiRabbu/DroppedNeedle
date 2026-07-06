import { API } from '$lib/constants';

// the current user is resolved server-side from the session cookie
export const FOLLOW_ENDPOINTS = {
	status: (mbid: string) => API.artist.follow(mbid),
	setFollow: (mbid: string) => API.artist.follow(mbid),
	autoDownload: (mbid: string) => API.artist.autoDownload(mbid),
	followedArtists: () => API.following.artists(),
	newReleases: (limit: number, offset: number) => API.following.newReleases(limit, offset),
	recentReleases: (days: number, limit: number) => API.following.recentReleases(days, limit),
	newReleasesUnseenCount: () => API.following.newReleasesUnseenCount(),
	markNewReleasesSeen: () => API.following.markNewReleasesSeen(),
	concerts: () => API.following.concerts(),
	concertCities: () => API.following.concertCities(),
	concertCitySearch: (q: string) => API.following.concertCitySearch(q),
	concertsUnseenCount: () => API.following.concertsUnseenCount(),
	markConcertsSeen: () => API.following.markConcertsSeen(),
	adminApprovals: () => API.requests.autoDownloadApprovals(),
	approve: (userId: string, mbid: string) => API.requests.approveAutoDownload(userId, mbid),
	reject: (userId: string, mbid: string) => API.requests.rejectAutoDownload(userId, mbid)
} as const;
