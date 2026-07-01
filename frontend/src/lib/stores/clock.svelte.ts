// A single shared 1-second clock for live countdowns (the Wanted "next spin in 11:58"
// timers), so every card ticks together off ONE interval instead of N. Read nowSeconds()
// inside a $derived/template to track it; start the tick from a browser $effect.
let nowMs = $state(Date.now());

export function nowSeconds(): number {
	return nowMs / 1000;
}

// Refcounted start: the first consumer opens the interval, the last to clean up closes it.
let consumers = 0;
let timer: ReturnType<typeof setInterval> | null = null;

export function startSharedClock(): () => void {
	consumers += 1;
	if (timer === null) {
		nowMs = Date.now();
		timer = setInterval(() => {
			nowMs = Date.now();
		}, 1000);
	}
	return () => {
		consumers -= 1;
		if (consumers <= 0 && timer !== null) {
			clearInterval(timer);
			timer = null;
			consumers = 0;
		}
	};
}
