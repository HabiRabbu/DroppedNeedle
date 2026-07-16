<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { artistHref } from '$lib/utils/entityRoutes';

	$effect(() => {
		const id = page.params.id;
		if (id) void goto(artistHref(id), { replaceState: true });
	});
</script>

<div class="container mx-auto p-4 md:p-6 lg:p-8">
	<div class="skeleton h-64 w-full rounded-box"></div>
</div>
