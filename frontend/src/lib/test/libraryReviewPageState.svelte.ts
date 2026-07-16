import { SvelteURL } from 'svelte/reactivity';

export const libraryReviewPage = $state({
	url: new SvelteURL('http://localhost/library/review'),
	params: {} as Record<string, string>
});

export function setLibraryReviewUrl(value: string): void {
	libraryReviewPage.url = new SvelteURL(value, 'http://localhost');
}
