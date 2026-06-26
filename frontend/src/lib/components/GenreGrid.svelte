<script lang="ts">
	import { imageSettingsStore } from '$lib/stores/imageSettings';
	import { appendAudioDBSizeSuffix } from '$lib/utils/imageSuffix';

	interface Props {
		title: string;
		genres: { name: string; listen_count?: number | null; artist_count?: number | null }[];
		genreArtistImages?: Record<string, string | null> | undefined;
	}

	let { title, genres, genreArtistImages = undefined }: Props = $props();

	const genreColors = [
		'from-rose-500/90 to-pink-700',
		'from-violet-500/90 to-purple-700',
		'from-blue-500/90 to-cyan-700',
		'from-emerald-500/90 to-teal-700',
		'from-amber-500/90 to-orange-700',
		'from-red-500/90 to-rose-700',
		'from-indigo-500/90 to-violet-700',
		'from-cyan-500/90 to-blue-700',
		'from-green-500/90 to-emerald-700',
		'from-orange-500/90 to-amber-700'
	];

	function getGenreColor(name: string): string {
		let hash = 0;
		for (let i = 0; i < name.length; i++) {
			hash = (hash * 31 + name.charCodeAt(i)) | 0;
		}
		return genreColors[Math.abs(hash) % genreColors.length];
	}

	function formatCount(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toString();
	}

	let cdnFailedSet = $state(new Set<string>());

	function onCdnError(genreName: string) {
		cdnFailedSet.add(genreName);
		cdnFailedSet = cdnFailedSet;
	}
</script>

<section>
	<div class="mb-4 flex items-center justify-between">
		<h2 class="text-lg font-bold sm:text-xl">{title}</h2>
	</div>
	<div class="grid grid-cols-2 gap-2.5 sm:grid-cols-3 sm:gap-3 md:grid-cols-4 lg:grid-cols-5">
		{#each genres.slice(0, 20) as genre (genre.name)}
			{@const cdnUrl = genreArtistImages?.[genre.name] ?? null}
			{@const useCdn =
				cdnUrl && $imageSettingsStore.directRemoteImagesEnabled && !cdnFailedSet.has(genre.name)}
			<a
				href="/genre?name={encodeURIComponent(genre.name)}"
				class="group relative isolate overflow-hidden rounded-xl text-white shadow-md transition-all duration-300 hover:shadow-xl hover:ring-2 hover:ring-white/20 active:scale-[0.97]"
			>
				<div class="aspect-16/10"></div>

				<div
					class="absolute inset-0 bg-linear-to-br {getGenreColor(genre.name)}"
					style="z-index: 1;"
				></div>

				{#if useCdn}
					<img
						src={appendAudioDBSizeSuffix(cdnUrl, 'lg')}
						alt=""
						class="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-50"
						style="z-index: 5;"
						loading="lazy"
						referrerpolicy="no-referrer"
						onerror={() => onCdnError(genre.name)}
					/>
				{/if}

				<div
					class="absolute inset-0 bg-linear-to-t from-black/70 via-black/20 to-transparent"
					style="z-index: 6;"
				></div>

				<div
					class="absolute inset-x-0 bottom-0 flex flex-col justify-end p-3 sm:p-4"
					style="z-index: 10;"
				>
					{#if genre.listen_count}
						<span class="mb-1 text-[10px] font-medium tracking-wide text-white/70 sm:text-xs">
							{formatCount(genre.listen_count)} plays
						</span>
					{/if}
					<h3 class="line-clamp-2 text-sm font-bold leading-tight drop-shadow-md sm:text-base">
						{genre.name}
					</h3>
				</div>

				<div
					class="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-inset ring-white/10 transition-all duration-300 group-hover:ring-white/25"
					style="z-index: 15;"
				></div>
			</a>
		{/each}
	</div>
</section>
