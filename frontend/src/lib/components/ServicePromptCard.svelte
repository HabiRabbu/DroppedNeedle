<script lang="ts">
	import type { ServicePrompt } from '$lib/types';
	import { ArrowRight, Headphones, Tv, Download, Radio, Music, X } from 'lucide-svelte';
	import { dismiss } from '$lib/utils/dismissedPrompts';
	import type { ComponentType } from 'svelte';

	const serviceIcons: Record<string, ComponentType> = {
		listenbrainz: Headphones,
		jellyfin: Tv,
		'download-client': Download,
		lastfm: Radio
	};

	const serviceBrandVars: Record<string, string> = {
		listenbrainz: '--brand-listenbrainz',
		jellyfin: '--brand-jellyfin',
		'download-client': 'accent',
		lastfm: '--brand-lastfm'
	};

	interface Props {
		prompt: ServicePrompt;
		ondismiss?: ((service: string) => void) | undefined;
	}

	let { prompt, ondismiss = undefined }: Props = $props();

	function getBorderColor(): string {
		const v = serviceBrandVars[prompt.service];
		if (!v) return 'border-l-base-content/30';
		if (v === 'accent') return 'border-l-accent';
		return '';
	}

	function getBorderStyle(): string {
		const v = serviceBrandVars[prompt.service];
		if (!v || v === 'accent') return '';
		return `border-left-color: rgb(var(${v}));`;
	}

	function getIconColor(): string {
		const v = serviceBrandVars[prompt.service];
		if (!v) return '';
		if (v === 'accent') return 'color: var(--color-accent);';
		return `color: rgb(var(${v}));`;
	}

	function getPromptButtonClass(color: string): string {
		switch (color) {
			case 'primary':
				return 'btn-primary';
			case 'secondary':
				return 'btn-secondary';
			case 'accent':
				return 'btn-accent';
			default:
				return 'btn-neutral';
		}
	}

	function getSettingsLink(service: string): string {
		// Per-user scrobble/discovery connections live on /profile, not the admin /settings tabs.
		if (service === 'listenbrainz' || service === 'lastfm') return '/profile#scrobbling';
		return `/settings?tab=${service}`;
	}

	function handleDismiss() {
		dismiss(prompt.service);
		ondismiss?.(prompt.service);
	}

	const SvelteComponent = $derived(serviceIcons[prompt.service] || Music);
</script>

<div
	class="card overflow-hidden border-l-4 bg-base-200/50 border border-base-300/50 shadow-sm {getBorderColor()}"
	style={getBorderStyle()}
>
	<div class="card-body flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-6 relative">
		<button
			class="absolute top-2 right-2 btn btn-ghost btn-xs btn-circle text-base-content/40 hover:text-base-content"
			onclick={handleDismiss}
			aria-label="Dismiss {prompt.title}"
			title="Dismiss"
		>
			<X class="h-3.5 w-3.5" />
		</button>
		<div class="shrink-0" style={getIconColor()}>
			<SvelteComponent class="h-10 w-10 sm:h-12 sm:w-12" />
		</div>
		<div class="min-w-0 flex-1 pr-6">
			<h3 class="card-title mb-1 text-base sm:text-lg">{prompt.title}</h3>
			<p class="mb-2 text-xs text-base-content/70 sm:mb-3 sm:text-sm">
				{prompt.description}
			</p>
			<div class="flex flex-wrap gap-1 sm:gap-2">
				{#each prompt.features as feature, i (`${feature}-${i}`)}
					<span class="badge badge-ghost badge-xs sm:badge-sm">{feature}</span>
				{/each}
			</div>
		</div>
		<div class="shrink-0">
			<a
				href={getSettingsLink(prompt.service)}
				class="btn btn-sm sm:btn-md {getPromptButtonClass(prompt.color)}"
			>
				Connect
				<ArrowRight class="h-4 w-4" />
			</a>
		</div>
	</div>
</div>
