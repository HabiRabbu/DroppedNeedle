import { describe, expect, it, beforeEach, vi } from 'vitest';
import { PAGE_SOURCE_KEYS, API } from '$lib/constants';

vi.mock('$app/environment', () => ({ browser: true }));

const storage = new Map<string, string>();
const mockLocalStorage = {
	getItem: vi.fn((key: string) => storage.get(key) ?? null),
	setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
	removeItem: vi.fn((key: string) => storage.delete(key)),
	clear: vi.fn(() => storage.clear()),
	get length() {
		return storage.size;
	},
	key: vi.fn((_i: number) => null)
};

vi.stubGlobal('localStorage', mockLocalStorage);
vi.stubGlobal('window', globalThis);

describe('migratePageSourceKeys', () => {
	let migratePageSourceKeys: (typeof import('$lib/stores/musicSource'))['migratePageSourceKeys'];

	beforeEach(async () => {
		vi.clearAllMocks();
		storage.clear();
		vi.resetModules();
		const mod = await import('$lib/stores/musicSource');
		migratePageSourceKeys = mod.migratePageSourceKeys;
	});

	it('converts raw "listenbrainz" to JSON-encoded string', () => {
		storage.set(PAGE_SOURCE_KEYS.home, 'listenbrainz');
		migratePageSourceKeys();
		expect(storage.get(PAGE_SOURCE_KEYS.home)).toBe('"listenbrainz"');
	});

	it('converts raw "lastfm" to JSON-encoded string', () => {
		storage.set(PAGE_SOURCE_KEYS.home, 'lastfm');
		migratePageSourceKeys();
		expect(storage.get(PAGE_SOURCE_KEYS.home)).toBe('"lastfm"');
	});

	it('leaves already-JSON-encoded values unchanged', () => {
		storage.set(PAGE_SOURCE_KEYS.home, '"listenbrainz"');
		migratePageSourceKeys();
		expect(storage.get(PAGE_SOURCE_KEYS.home)).toBe('"listenbrainz"');
	});

	it('leaves invalid values unchanged', () => {
		storage.set(PAGE_SOURCE_KEYS.home, 'plex');
		migratePageSourceKeys();
		expect(storage.get(PAGE_SOURCE_KEYS.home)).toBe('plex');
	});

	it('handles absent keys without error', () => {
		expect(() => migratePageSourceKeys()).not.toThrow();
	});

	it('migrates all page source keys', () => {
		for (const key of Object.values(PAGE_SOURCE_KEYS)) {
			storage.set(key, 'lastfm');
		}
		migratePageSourceKeys();
		for (const key of Object.values(PAGE_SOURCE_KEYS)) {
			expect(storage.get(key)).toBe('"lastfm"');
		}
	});
});

describe('isMusicSource', () => {
	let isMusicSource: (typeof import('$lib/stores/musicSource'))['isMusicSource'];

	beforeEach(async () => {
		vi.resetModules();
		const mod = await import('$lib/stores/musicSource');
		isMusicSource = mod.isMusicSource;
	});

	it('returns true for listenbrainz', () => {
		expect(isMusicSource('listenbrainz')).toBe(true);
	});

	it('returns true for lastfm', () => {
		expect(isMusicSource('lastfm')).toBe(true);
	});

	it('returns false for undefined', () => {
		expect(isMusicSource(undefined)).toBe(false);
	});

	it('returns false for invalid string', () => {
		expect(isMusicSource('plex')).toBe(false);
	});

	it('returns false for null', () => {
		expect(isMusicSource(null)).toBe(false);
	});
});

describe('API.home', () => {
	it('is the unified endpoint with no source param', () => {
		expect(API.home()).toBe('/api/v1/home');
	});
});
