import { defineConfig, devices } from '@playwright/test';

// Playwright E2E config for the native download flow. This suite is intentionally
// NOT part of `make ci` (it needs a running DroppedNeedle stack + a slskd mock); run it
// with `make frontend-test-e2e` against a live instance. Point it at your stack with
// DROPPEDNEEDLE_E2E_BASE_URL (default http://localhost:8688).
const baseURL = process.env.DROPPEDNEEDLE_E2E_BASE_URL ?? 'http://localhost:8688';

export default defineConfig({
	testDir: './tests/e2e',
	timeout: 30_000,
	fullyParallel: false,
	retries: 0,
	reporter: 'list',
	use: {
		baseURL,
		trace: 'on-first-retry'
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
});
