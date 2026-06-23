let reducedMotion =
	typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (typeof window !== 'undefined') {
	window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (e) => {
		reducedMotion = e.matches;
	});
}

export interface TiltOptions {
	/** Full CSS colour for the shadow glow, e.g. 'var(--color-primary)' or 'var(--color-secondary)' */
	shadowColorVar?: string;
}

/**
 * Svelte action that adds a 3D tilt effect with specular highlight to an element.
 *
 * Sets CSS custom properties on the node that the component template can consume:
 * - `--tilt-transform` - the rotateX/rotateY transform string
 * - `--tilt-specular-bg` - radial-gradient for the specular highlight
 * - `--tilt-shadow` - box-shadow value (changes on hover)
 *
 * Respects `prefers-reduced-motion: reduce` reactively.
 */
export function tilt(node: HTMLElement, options?: TiltOptions) {
	const color = options?.shadowColorVar ?? 'var(--color-primary)';

	node.style.setProperty('--tilt-shadow', `0 4px 16px oklch(from ${color} l c h / 0.06)`);

	function handlePointerMove(e: PointerEvent) {
		if (reducedMotion) return;
		const rect = node.getBoundingClientRect();
		const x = e.clientX - rect.left;
		const y = e.clientY - rect.top;
		const centerX = rect.width / 2;
		const centerY = rect.height / 2;
		const rotateY = ((x - centerX) / centerX) * 4;
		const rotateX = ((centerY - y) / centerY) * 3;
		node.style.setProperty(
			'--tilt-transform',
			`rotateX(${rotateX.toFixed(1)}deg) rotateY(${rotateY.toFixed(1)}deg) translateZ(0)`
		);
		const pctX = ((x / rect.width) * 100).toFixed(0);
		const pctY = ((y / rect.height) * 100).toFixed(0);
		node.style.setProperty(
			'--tilt-specular-bg',
			`radial-gradient(circle at ${pctX}% ${pctY}%, rgba(255,255,255,0.08) 0%, transparent 60%)`
		);
		node.style.setProperty('--tilt-shadow', `0 12px 48px oklch(from ${color} l c h / 0.2)`);
	}

	function handlePointerLeave() {
		node.style.removeProperty('--tilt-transform');
		node.style.removeProperty('--tilt-specular-bg');
		node.style.setProperty('--tilt-shadow', `0 4px 16px oklch(from ${color} l c h / 0.06)`);
	}

	node.addEventListener('pointermove', handlePointerMove);
	node.addEventListener('pointerleave', handlePointerLeave);

	return {
		destroy() {
			node.removeEventListener('pointermove', handlePointerMove);
			node.removeEventListener('pointerleave', handlePointerLeave);
			node.style.removeProperty('--tilt-transform');
			node.style.removeProperty('--tilt-specular-bg');
			node.style.removeProperty('--tilt-shadow');
		}
	};
}
