import { writable } from 'svelte/store';

interface ErrorModalState {
	show: boolean;
	title: string;
	message: string;
	details: string;
}

function createErrorModalStore() {
	const { subscribe, set, update } = writable<ErrorModalState>({
		show: false,
		title: '',
		message: '',
		details: ''
	});

	return {
		subscribe,
		show: (title: string, message: string, details: string = '') => {
			set({ show: true, title, message, details });
		},
		hide: () => {
			update((state) => ({ ...state, show: false }));
		},
		reset: () => {
			set({ show: false, title: '', message: '', details: '' });
		}
	};
}

export const errorModal = createErrorModalStore();
