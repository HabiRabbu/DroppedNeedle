<script lang="ts">
	interface Zone {
		id: string;
		label: string;
	}

	interface Props {
		zones: Zone[];
	}

	let { zones }: Props = $props();

	function jump(id: string) {
		const el = document.getElementById(id);
		if (!el) return;
		const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
	}
</script>

{#if zones.length > 1}
	<nav
		class="sticky top-0 z-30 -mx-4 mb-2 border-b border-base-content/5 bg-base-100/85 px-4 py-2 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
		aria-label="Jump to a discover section"
	>
		<div class="flex gap-1.5 overflow-x-auto">
			{#each zones as zone (zone.id)}
				<button
					class="btn btn-ghost btn-xs shrink-0 whitespace-nowrap rounded-full border border-base-content/10 font-medium text-base-content/60 hover:border-primary/30 hover:text-primary"
					onclick={() => jump(zone.id)}
				>
					{zone.label}
				</button>
			{/each}
		</div>
	</nav>
{/if}
