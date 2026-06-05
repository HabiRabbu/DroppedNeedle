<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import {
		UserRound,
		ShieldCheck,
		UserCheck,
		UserX,
		Plus,
		Eye,
		EyeOff,
		RefreshCw
	} from 'lucide-svelte';

	interface UserRecord {
		id: string;
		display_name: string;
		role: 'admin' | 'trusted' | 'user';
		email: string | null;
	}

	let users = $state<UserRecord[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let savingRole = $state<string | null>(null); // user_id being updated

	// Create user form
	let showCreateForm = $state(false);
	let newName = $state('');
	let newEmail = $state('');
	let newPassword = $state('');
	let newRole = $state<'admin' | 'trusted' | 'user'>('user');
	let showNewPassword = $state(false);
	let creating = $state(false);
	let createError = $state<string | null>(null);
	let createSuccess = $state<string | null>(null);

	async function loadUsers() {
		loading = true;
		error = null;
		try {
			const data = await api.get<{ users: UserRecord[]; total: number }>('/api/v1/auth/admin/users');
			users = data.users;
		} catch {
			error = "Couldn't load users";
		} finally {
			loading = false;
		}
	}

	async function setRole(userId: string, role: 'admin' | 'trusted' | 'user') {
		savingRole = userId;
		try {
			await api.patch(`/api/v1/auth/admin/users/${userId}/role`, { role });
			users = users.map((u) => (u.id === userId ? { ...u, role } : u));
		} catch {
			// ignore, could show a toast but keeping it simple
		} finally {
			savingRole = null;
		}
	}

	async function handleCreateUser() {
		createError = null;
		createSuccess = null;
		if (newPassword.length < 12) {
			createError = 'Password must be at least 12 characters';
			return;
		}
		creating = true;
		try {
			const user = await api.post<UserRecord>('/api/v1/auth/admin/users', {
				display_name: newName,
				email: newEmail,
				password: newPassword,
				role: newRole,
			});
			users = [...users, user];
			createSuccess = `Created ${user.display_name}`;
			newName = '';
			newEmail = '';
			newPassword = '';
			newRole = 'user';
			showCreateForm = false;
		} catch (e: unknown) {
			const msg = (e as { message?: string })?.message;
			createError = msg ?? 'Could not create user';
		} finally {
			creating = false;
		}
	}

	const roleLabel: Record<string, string> = {
		admin: 'Admin',
		trusted: 'Trusted',
		user: 'User',
	};

	function roleIcon(role: string) {
		if (role === 'admin') return ShieldCheck;
		if (role === 'trusted') return UserCheck;
		return UserX;
	}

	function roleBadgeClass(role: string) {
		if (role === 'admin') return 'badge-accent';
		if (role === 'trusted') return 'badge-info';
		return 'badge-ghost';
	}

	onMount(() => {
		void loadUsers();
	});
</script>

<div class="bg-base-200 rounded-box p-6 space-y-6">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-lg font-semibold">User Management</h2>
			<p class="text-sm text-base-content/50 mt-0.5">Manage accounts and roles.</p>
		</div>
		<div class="flex gap-2">
			<button
				class="btn btn-ghost btn-sm btn-circle"
				onclick={() => void loadUsers()}
				aria-label="Refresh"
				disabled={loading}
			>
				<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
			</button>
			<button
				class="btn btn-primary btn-sm gap-1"
				onclick={() => (showCreateForm = !showCreateForm)}
			>
				<Plus class="h-4 w-4" />
				New User
			</button>
		</div>
	</div>

	{#if showCreateForm}
		<div class="bg-base-300/50 rounded-box p-4 border border-base-300">
			<h3 class="text-sm font-semibold mb-4 text-base-content/70 uppercase tracking-wider">
				Create User
			</h3>
			<form
				onsubmit={(e) => { e.preventDefault(); void handleCreateUser(); }}
				class="grid grid-cols-1 sm:grid-cols-2 gap-3"
			>
				<fieldset class="fieldset">
					<legend class="fieldset-legend">Display Name</legend>
					<input
						type="text"
						class="input input-bordered w-full input-sm"
						bind:value={newName}
						required
						placeholder="Jane Smith"
					/>
				</fieldset>
				<fieldset class="fieldset">
					<legend class="fieldset-legend">Email</legend>
					<input
						type="email"
						class="input input-bordered w-full input-sm"
						bind:value={newEmail}
						required
						placeholder="jane@example.com"
					/>
				</fieldset>
				<fieldset class="fieldset">
					<legend class="fieldset-legend">Password</legend>
					<label class="input input-bordered flex items-center gap-2 w-full input-sm">
						{#if showNewPassword}
							<input type="text" class="grow" bind:value={newPassword} required placeholder="Min. 12 chars" />
						{:else}
							<input type="password" class="grow" bind:value={newPassword} required placeholder="Min. 12 chars" />
						{/if}
						<button
							type="button"
							onclick={() => (showNewPassword = !showNewPassword)}
							class="opacity-50 hover:opacity-100"
							aria-label="Toggle"
						>
							{#if showNewPassword}<EyeOff class="h-3.5 w-3.5" />{:else}<Eye class="h-3.5 w-3.5" />{/if}
						</button>
					</label>
				</fieldset>
				<fieldset class="fieldset">
					<legend class="fieldset-legend">Role</legend>
					<select class="select select-bordered w-full select-sm" bind:value={newRole}>
						<option value="user">User</option>
						<option value="trusted">Trusted</option>
						<option value="admin">Admin</option>
					</select>
				</fieldset>
				{#if createError}
					<div class="sm:col-span-2 alert alert-error py-2 text-sm">{createError}</div>
				{/if}
				<div class="sm:col-span-2 flex gap-2 justify-end">
					<button type="button" class="btn btn-ghost btn-sm" onclick={() => (showCreateForm = false)}>
						Cancel
					</button>
					<button type="submit" class="btn btn-primary btn-sm" disabled={creating}>
						{#if creating}<span class="loading loading-spinner loading-xs"></span>{/if}
						Create
					</button>
				</div>
			</form>
		</div>
	{/if}

	{#if createSuccess}
		<div class="alert alert-success py-2 text-sm">{createSuccess}</div>
	{/if}

	{#if error}
		<div class="alert alert-error py-2 text-sm">{error}</div>
	{/if}

	{#if loading && users.length === 0}
		<div class="space-y-2">
			{#each Array(3) as _, i (`user-skel-${i}`)}
				<div class="flex items-center gap-3 p-3 bg-base-300/40 rounded-box animate-pulse">
					<div class="w-9 h-9 rounded-full bg-base-300"></div>
					<div class="flex-1">
						<div class="h-3.5 bg-base-300 rounded w-32 mb-1.5"></div>
						<div class="h-3 bg-base-300 rounded w-48"></div>
					</div>
					<div class="h-6 bg-base-300 rounded-full w-16"></div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="space-y-1.5">
			{#each users as user (user.id)}
				{@const RoleIcon = roleIcon(user.role)}
				<div class="flex items-center gap-3 p-3 bg-base-300/30 rounded-box hover:bg-base-300/50 transition-colors">
					<div class="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
						<UserRound class="h-5 w-5 text-primary/60" />
					</div>
					<div class="flex-1 min-w-0">
						<p class="text-sm font-medium truncate">{user.display_name}</p>
						{#if user.email}
							<p class="text-xs text-base-content/50 truncate">{user.email}</p>
						{/if}
					</div>
					<div class="flex items-center gap-2 shrink-0">
						<span class="badge {roleBadgeClass(user.role)} badge-sm gap-1">
							<RoleIcon class="h-3 w-3" />
							{roleLabel[user.role]}
						</span>
						{#if savingRole === user.id}
							<span class="loading loading-spinner loading-xs"></span>
						{:else}
							<select
								class="select select-bordered select-xs"
								value={user.role}
								onchange={(e) => void setRole(user.id, (e.target as HTMLSelectElement).value as 'admin' | 'trusted' | 'user')}
								aria-label="Change role"
							>
								<option value="user">User</option>
								<option value="trusted">Trusted</option>
								<option value="admin">Admin</option>
							</select>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<div class="pt-2 border-t border-base-300 space-y-2">
		<h3 class="text-xs font-semibold text-base-content/50 uppercase tracking-wider">Role guide</h3>
		<div class="grid gap-2 text-xs text-base-content/60">
			<div class="flex gap-2">
				<ShieldCheck class="h-4 w-4 text-accent shrink-0 mt-0.5" />
				<span><strong class="text-base-content/80">Admin</strong>, full access, approves requests, manages users.</span>
			</div>
			<div class="flex gap-2">
				<UserCheck class="h-4 w-4 text-info shrink-0 mt-0.5" />
				<span><strong class="text-base-content/80">Trusted</strong>, requests auto-approved, no admin functions.</span>
			</div>
			<div class="flex gap-2">
				<UserX class="h-4 w-4 text-base-content/40 shrink-0 mt-0.5" />
				<span><strong class="text-base-content/80">User</strong>, requests need admin approval before downloading.</span>
			</div>
		</div>
	</div>
</div>
