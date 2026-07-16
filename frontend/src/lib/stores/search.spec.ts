import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: true, building: false, dev: false, version: '' }));

import { CACHE_KEYS } from '$lib/constants';
import { searchStore } from './search';

class MemoryStorage implements Storage {
	private readonly values = new Map<string, string>();

	get length(): number {
		return this.values.size;
	}

	clear(): void {
		this.values.clear();
	}

	getItem(key: string): string | null {
		return this.values.get(key) ?? null;
	}

	key(index: number): string | null {
		return [...this.values.keys()][index] ?? null;
	}

	removeItem(key: string): void {
		this.values.delete(key);
	}

	setItem(key: string, value: string): void {
		this.values.set(key, value);
	}
}

beforeEach(() => {
	Object.defineProperty(globalThis, 'localStorage', {
		configurable: true,
		value: new MemoryStorage()
	});
});

describe('searchStore persistent cache', () => {
	it('clears every saved query without removing other browser data', () => {
		searchStore.setResults('Blue Train', [], []);
		searchStore.setResults('Kind of Blue', [], []);
		localStorage.setItem('unrelated', 'keep');
		expect(
			Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
				(key) => key?.startsWith(`${CACHE_KEYS.SEARCH}_`)
			)
		).toHaveLength(2);

		searchStore.clear();

		expect(localStorage.getItem('unrelated')).toBe('keep');
		expect(
			Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
				(key) => key?.startsWith(`${CACHE_KEYS.SEARCH}_`)
			)
		).toEqual([]);
	});
});
