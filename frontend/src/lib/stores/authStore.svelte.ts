export interface AuthUser {
	id: string;
	display_name: string;
	role: 'admin' | 'trusted' | 'user';
	email: string | null;
	avatar_url: string | null;
}

function createAuthStore() {
	let user = $state<AuthUser | null>(null);
	let initialized = $state(false);

	return {
		get user() {
			return user;
		},
		get initialized() {
			return initialized;
		},
		get isAuthenticated() {
			return user !== null;
		},
		get isAdmin() {
			return user?.role === 'admin';
		},
		get isTrusted() {
			return user?.role === 'trusted' || user?.role === 'admin';
		},

		setUser(newUser: AuthUser) {
			user = newUser;
		},

		clear() {
			user = null;
		},

		markInitialized() {
			initialized = true;
		}
	};
}

export const authStore = createAuthStore();
