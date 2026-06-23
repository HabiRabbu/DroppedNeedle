import { get, writable } from 'svelte/store';
import { API } from '$lib/constants';
import { api } from '$lib/api/client';
import type { DownloadClientStatus } from '$lib/types';

interface IntegrationStatus {
	download_client: boolean;
	library: boolean;
	jellyfin: boolean;
	navidrome: boolean;
	plex: boolean;
	youtube: boolean;
	youtube_api: boolean;
	localfiles: boolean;
	loaded: boolean;
}

function createIntegrationStore() {
	const { subscribe, set, update } = writable<IntegrationStatus>({
		download_client: false,
		library: false,
		jellyfin: false,
		navidrome: false,
		plex: false,
		youtube: false,
		youtube_api: false,
		localfiles: false,
		loaded: false
	});
	let loadPromise: Promise<void> | null = null;

	return {
		subscribe,
		setStatus: (status: Partial<IntegrationStatus>) => {
			update((current) => ({ ...current, ...status, loaded: true }));
		},
		setDownloadClientConfigured: (configured: boolean) => {
			update((current) => ({ ...current, download_client: configured }));
		},
		reset: () => {
			set({
				download_client: false,
				library: false,
				jellyfin: false,
				navidrome: false,
				plex: false,
				youtube: false,
				youtube_api: false,
				localfiles: false,
				loaded: false
			});
		},
		ensureLoaded: async () => {
			const current = get({ subscribe });
			if (current.loaded) return;
			if (loadPromise) return loadPromise;

			loadPromise = (async () => {
				try {
					const status = await api.global.get<Partial<IntegrationStatus>>(
						API.homeIntegrationStatus()
					);
					update((state) => ({ ...state, ...status, loaded: true }));
				} catch {
					update((state) => ({ ...state, loaded: true }));
				}

				// drive download_client off the real slskd health check, not config presence; non-blocking so a slow/unreachable slskd never stalls the load
				api.global
					.get<DownloadClientStatus>(API.downloadClient.status())
					.then((dc) =>
						update((state) => ({ ...state, download_client: dc.client.status === 'ok' }))
					)
					.catch(() => {});
			})().finally(() => {
				loadPromise = null;
			});

			return loadPromise;
		}
	};
}

export const integrationStore = createIntegrationStore();
