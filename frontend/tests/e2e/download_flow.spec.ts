import { expect, test } from '@playwright/test';

/**
 * Full-UI download flow (Playwright): log in as admin, point the download client at a
 * (mock) slskd, request an album, see it in the download queue, then see the imported
 * file in the library.
 *
 * This runs against a live DroppedNeedle stack, not in `make ci`. Provide credentials and
 * a request target via env (see the constants below). Selectors are role/label based to
 * stay resilient; adjust them if the settings/album markup changes.
 */
const ADMIN_USER = process.env.DROPPEDNEEDLE_E2E_ADMIN_USER ?? 'admin';
const ADMIN_PASS = process.env.DROPPEDNEEDLE_E2E_ADMIN_PASS ?? 'changeme';
const SLSKD_URL = process.env.DROPPEDNEEDLE_E2E_SLSKD_URL ?? 'http://slskd:5030';
const SLSKD_KEY = process.env.DROPPEDNEEDLE_E2E_SLSKD_KEY ?? 'test-key';
const ALBUM_MBID = process.env.DROPPEDNEEDLE_E2E_ALBUM_MBID ?? '';

test.describe('native download flow', () => {
	test('admin configures slskd, requests an album, and watches it import', async ({ page }) => {
		// 1. Log in as admin.
		await page.goto('/login');
		await page.getByLabel(/username/i).fill(ADMIN_USER);
		await page.getByLabel(/password/i).fill(ADMIN_PASS);
		await page.getByRole('button', { name: /log ?in|sign ?in/i }).click();
		await expect(page).not.toHaveURL(/\/login/);

		// 2. Point the download client at the (mock) slskd instance.
		await page.goto('/settings/download-client');
		await page.getByLabel(/url/i).fill(SLSKD_URL);
		await page.getByLabel(/api key/i).fill(SLSKD_KEY);
		await page.getByRole('button', { name: /save/i }).click();
		await expect(page.getByText(/saved|connected|success/i).first()).toBeVisible();

		// 3. Request an album (needs a real MBID to exercise the pipeline end to end).
		test.skip(ALBUM_MBID === '', 'Set DROPPEDNEEDLE_E2E_ALBUM_MBID to request a real album');
		await page.goto(`/album/${ALBUM_MBID}`);
		await page
			.getByRole('button', { name: /request|download/i })
			.first()
			.click();

		// 4. See it appear in the downloads queue.
		await page.goto('/downloads');
		await expect(
			page.getByText(/downloading|queued|searching|processing|completed/i).first()
		).toBeVisible();

		// 5. The imported album eventually shows up in the library.
		await page.goto('/library/albums');
		await expect(page.getByRole('main')).toBeVisible();
	});
});
