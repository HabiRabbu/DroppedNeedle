import { page } from '@vitest/browser/context';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import type { LibraryManagementSettingsResponse } from '$lib/queries/library-management/types';

const h = vi.hoisted(() => ({
	settings: { data: {}, isLoading: false, isError: false, refetch: vi.fn() } as Record<
		string,
		unknown
	>,
	activation: { data: null, isLoading: false, refetch: vi.fn() } as Record<string, unknown>,
	validate: vi.fn(),
	impact: vi.fn(),
	update: vi.fn(),
	copy: vi.fn(),
	deleteProfile: vi.fn(),
	createActivation: vi.fn(),
	confirmActivation: vi.fn(),
	purgeImpact: vi.fn(),
	purge: vi.fn(),
	purgeData: null as Record<string, unknown> | null
}));

vi.mock('$lib/stores/authStore.svelte', () => ({
	authStore: { isAdmin: true, user: { id: 'admin-1' } }
}));
vi.mock('$lib/queries/library-management/LibraryManagementQueries.svelte', () => ({
	getLibraryManagementSettingsQuery: () => h.settings,
	getLibraryManagementActivationPreviewQuery: () => h.activation
}));
vi.mock('$lib/queries/library-management/LibraryManagementMutations.svelte', () => ({
	updateLibraryManagementSettingsMutation: () => ({ mutateAsync: h.update, isPending: false }),
	validateLibraryManagementSettingsMutation: () => ({ mutateAsync: h.validate, isPending: false }),
	previewLibraryManagementSettingsImpactMutation: () => ({
		mutateAsync: h.impact,
		isPending: false
	}),
	copyLibraryManagementProfileMutation: () => ({ mutateAsync: h.copy, isPending: false }),
	deleteLibraryManagementProfileMutation: () => ({
		mutateAsync: h.deleteProfile,
		isPending: false
	}),
	createLibraryManagementActivationPreviewMutation: () => ({
		mutateAsync: h.createActivation,
		isPending: false
	}),
	confirmLibraryManagementActivationMutation: () => ({
		mutateAsync: h.confirmActivation,
		isPending: false
	}),
	previewLibraryManagementBaselinePurgeMutation: () => ({
		mutateAsync: h.purgeImpact,
		isPending: false,
		get data() {
			return h.purgeData;
		}
	}),
	purgeLibraryManagementBaselinesMutation: () => ({ mutateAsync: h.purge, isPending: false })
}));

import SettingsLibraryManagement from './SettingsLibraryManagement.svelte';

const profileId = 'c2741223-da7c-5231-bcf5-7cead27b07d9';
const namingScriptId = 'f66f6409-ba0c-5b9a-9258-8fb91eefcb0b';

function baseSettings(): LibraryManagementSettingsResponse {
	return {
		schema_version: 1,
		profiles: [
			{
				id: profileId,
				name: 'Picard-style Organizer',
				description: 'Canonical tags, artwork, and same-root organization.',
				preset_origin: 'picard_style_organizer',
				preset_version: 1,
				revision: 'profile-1',
				metadata: {
					enabled: true,
					fields: [{ field: 'title', mode: 'merge', clear_when_canonical_missing: false }],
					artist_credits: {
						standardization: 'credited',
						translate_names: false,
						preferred_locales: []
					},
					relationships: { enabled: true, types: ['composer', 'performer'] },
					tagging_script_ids: [],
					preserve_fields: [],
					scrub_unmanaged_tags: false,
					preserve_embedded_art_during_scrub: true,
					format_compatibility: {
						id3_version: '2.4',
						id3v23_join_delimiter: '; ',
						id3_text_encoding: 'utf8',
						remove_id3_from_flac: false,
						mp3_apev2_policy: 'preserve',
						raw_aac_tag_policy: 'save_apev2',
						wav_tag_policy: 'id3',
						constrained_genres_primary_only: false
					}
				},
				genres: {
					enabled: true,
					mode: 'replace',
					sources: ['musicbrainz', 'listenbrainz'],
					maximum_count: 5,
					musicbrainz_minimum_count: 1,
					listenbrainz_minimum_count: 1,
					lastfm_minimum_weight: 10,
					listenbrainz_curated_only: true,
					lastfm_whitelist_only: true,
					canonicalize: true,
					maximum_ancestry_depth: 4,
					allowlist: [],
					denylist: [],
					aliases: [],
					preferred_casing: [],
					write_primary_only_for_constrained_formats: false
				},
				artwork: {
					embedded_enabled: true,
					external_enabled: true,
					providers: ['cover_art_archive_release', 'local_files'],
					approved_only: true,
					download_size: 'full',
					local_file_patterns: ['cover.jpg'],
					image_types: ['front'],
					minimum_width: 0,
					minimum_height: 0,
					embedded_maximum_size: 1200,
					embedded_format: 'jpeg',
					external_maximum_size: 0,
					external_format: 'original',
					embedded_front_only: true,
					external_front_only: true,
					never_replace_with_smaller: true,
					preserve_existing_types: [],
					external_naming_script_id: null,
					overwrite_external_files: false
				},
				organization: {
					rename_enabled: true,
					move_enabled: true,
					naming_script_id: namingScriptId,
					compatibility: {
						windows_compatible: true,
						replace_non_ascii: false,
						replace_spaces_with_underscores: false,
						separator_replacement: '_',
						maximum_component_length: 240,
						maximum_path_length: 4096,
						unicode_normalization: 'NFC',
						extension_case: 'preserve',
						windows_legacy_path_limit: false
					},
					move_sidecars: true,
					sidecar_patterns: ['*.cue'],
					source_cleanup: 'remove_after_confirmed_move',
					remove_empty_directories: true
				},
				file_behavior: {
					preserve_timestamps: true,
					preserve_permissions: true,
					strict_capability_gate: true,
					reject_symlinks: true,
					validate_written_metadata: true,
					validate_technical_audio: true
				},
				enrichment: {
					lyrics: {
						enabled: false,
						provider: 'lrclib',
						write_plain: true,
						write_synced: true,
						required: false
					},
					replaygain: { enabled: false, mode: 'preserve', album_aware: true, required: false }
				},
				notification: { refresh_droppedneedle: true, refresh_external_servers: false }
			}
		],
		default_profile_id: profileId,
		root_assignments: [],
		naming_scripts: [
			{
				id: namingScriptId,
				name: 'Picard-style folders',
				source: '{albumartist}/{album} ({year})/{track:02} {title}.{ext}',
				revision: 'script-1',
				preset_origin: 'picard_style_organizer',
				preset_version: 1
			}
		],
		tagging_scripts: [],
		undo_retention_days: 90,
		preview_retention_hours: 24,
		recycle_bin_path: '',
		external_refresh: {
			enabled: false,
			plex_enabled: false,
			jellyfin_enabled: false,
			navidrome_enabled: false,
			retry_attempts: 3,
			retry_delay_seconds: 30
		},
		settings_revision: 'settings-1'
	};
}

const roots = [
	{
		id: 'root-1',
		path: '/music/archive',
		label: 'Archive',
		policy: 'automatic' as const,
		rules: []
	}
];

beforeEach(() => {
	vi.clearAllMocks();
	h.purgeData = null;
	const settings = baseSettings();
	h.settings = { data: settings, isLoading: false, isError: false, refetch: vi.fn() };
	h.activation = { data: null, isLoading: false, refetch: vi.fn() };
	const harmless = {
		current_settings_revision: 'settings-1',
		proposed_settings_revision: 'settings-2',
		stale: false,
		classification: 'harmless',
		preview_required: false,
		affected_root_ids: [],
		reasons: []
	};
	h.validate.mockResolvedValue(harmless);
	h.impact.mockResolvedValue(harmless);
	h.update.mockResolvedValue({ ...settings, settings_revision: 'settings-2' });
	h.createActivation.mockResolvedValue({
		job_id: 'preview-1',
		preview_token: 'token-1',
		expires_at: 2_000_000_000,
		operation_revision: 1
	});
	h.confirmActivation.mockResolvedValue({ ...settings, settings_revision: 'settings-2' });
});

describe('SettingsLibraryManagement', () => {
	it('starts off everywhere and preserves subordinate profile values while a master toggle is off', async () => {
		render(SettingsLibraryManagement, { roots, policyRevision: 'policy-1' });
		await expect.element(page.getByText('Off everywhere')).toBeVisible();
		await expect.element(page.getByText('Scanning: Automatic identification')).toBeVisible();

		await page.getByRole('button', { name: 'Edit' }).click();
		const profileDialog = page.getByRole('dialog', { name: 'Picard-style Organizer' });
		await expect
			.element(profileDialog.getByRole('heading', { name: 'Picard-style Organizer' }))
			.toHaveFocus();
		const metadataToggle = profileDialog.getByRole('checkbox', { name: /Manage metadata tags/ });
		await metadataToggle.click();
		await expect
			.element(profileDialog.getByRole('combobox', { name: 'Mode for title' }))
			.not.toBeInTheDocument();
		await metadataToggle.click();
		await expect
			.element(profileDialog.getByRole('combobox', { name: 'Mode for title' }))
			.toHaveValue('merge');

		await profileDialog.getByText('Lyrics and loudness').click();
		const lyricsToggle = profileDialog.getByRole('checkbox', {
			name: /Fetch lyrics from LRCLIB/
		});
		const plainLyrics = profileDialog.getByRole('checkbox', { name: /Write plain lyrics/ });
		await expect.element(plainLyrics).toBeDisabled();
		await lyricsToggle.click();
		await expect.element(plainLyrics).toBeEnabled();
		await expect.element(plainLyrics).toBeChecked();

		const replayGainToggle = profileDialog.getByRole('checkbox', {
			name: /Manage ReplayGain/
		});
		const replayGainMode = profileDialog.getByRole('combobox', {
			name: 'Existing ReplayGain values'
		});
		await expect.element(replayGainMode).toBeDisabled();
		await replayGainToggle.click();
		await expect.element(replayGainMode).toBeEnabled();
		await expect.element(replayGainMode).toHaveValue('preserve');
	});

	it('requires a current dry run and exact phrase before first automatic activation', async () => {
		h.impact.mockResolvedValue({
			current_settings_revision: 'settings-1',
			proposed_settings_revision: 'settings-2',
			stale: false,
			classification: 'destructive',
			preview_required: true,
			affected_root_ids: ['root-1'],
			reasons: ['automatic trigger enabled']
		});
		h.activation = {
			data: {
				job_id: 'preview-1',
				state: 'ready',
				ready_for_confirmation: true,
				expired: false,
				stale: false,
				summary: {
					eligible_count: 8,
					warning_count: 1,
					blocked_count: 0,
					path_change_count: 7
				}
			},
			isLoading: false,
			refetch: vi.fn()
		};

		render(SettingsLibraryManagement, { roots, policyRevision: 'policy-1' });
		await page.getByRole('checkbox', { name: /Configure Library Management/ }).click();
		await page.getByRole('checkbox', { name: /Acquisitions/ }).click();
		await page.getByRole('button', { name: 'Validate and save' }).click();

		expect(h.update).not.toHaveBeenCalled();
		await expect
			.element(page.getByRole('heading', { name: 'Enable Library Management' }))
			.toHaveFocus();
		await page.getByRole('button', { name: 'Run dry run' }).click();
		await expect.element(page.getByText('Eligible').first()).toBeVisible();
		await page.getByRole('button', { name: 'Use this dry run' }).click();

		const enableButton = page.getByRole('button', { name: 'Enable Library Management' });
		await expect.element(enableButton).toBeDisabled();
		await page
			.getByRole('textbox', { name: /Type Enable Library Management/ })
			.fill('Enable Library Management');
		await expect.element(enableButton).toBeEnabled();
		await enableButton.click();
		expect(h.confirmActivation).toHaveBeenCalledWith(
			expect.objectContaining({
				confirmation: true,
				proofs: [{ root_id: 'root-1', job_id: 'preview-1', preview_token: 'token-1' }]
			})
		);
	});

	it('does not accept an expired or stale activation preview', async () => {
		h.impact.mockResolvedValue({
			current_settings_revision: 'settings-1',
			proposed_settings_revision: 'settings-2',
			stale: false,
			classification: 'destructive',
			preview_required: true,
			affected_root_ids: ['root-1'],
			reasons: []
		});
		h.activation = {
			data: {
				job_id: 'preview-1',
				state: 'ready',
				ready_for_confirmation: true,
				expired: true,
				stale: true,
				summary: { eligible_count: 8, warning_count: 0, blocked_count: 0, path_change_count: 8 }
			},
			isLoading: false,
			refetch: vi.fn()
		};

		render(SettingsLibraryManagement, { roots, policyRevision: 'policy-1' });
		await page.getByRole('checkbox', { name: /Configure Library Management/ }).click();
		await page.getByRole('checkbox', { name: /Acquisitions/ }).click();
		await page.getByRole('button', { name: 'Validate and save' }).click();
		await page.getByRole('button', { name: 'Run dry run' }).click();
		await expect.element(page.getByText(/stale or expired/)).toBeVisible();
		await expect.element(page.getByRole('button', { name: 'Use this dry run' })).toBeDisabled();
		expect(h.confirmActivation).not.toHaveBeenCalled();
	});

	it('keeps irreversible baseline purge in advanced retention with impact and typed confirmation', async () => {
		h.purgeData = {
			baseline_count: 14,
			referenced_blob_count: 9,
			referenced_blob_bytes: 4096,
			blocked_journal_count: 0,
			active_restore_count: 0,
			catalog_revision: 7,
			impact_token: 'impact-token'
		};
		h.purgeImpact.mockResolvedValue(h.purgeData);
		h.purge.mockResolvedValue({
			purged_baseline_count: 14,
			detached_reference_count: 9,
			cleaned_blob_count: 9,
			existing: false
		});

		render(SettingsLibraryManagement, { roots, policyRevision: 'policy-1' });
		await page.getByText('Retention, recycle, and refresh').click();
		await page.getByRole('button', { name: 'Purge baselines...' }).click();
		await expect
			.element(page.getByRole('heading', { name: 'Purge first-management baselines?' }))
			.toHaveFocus();
		await expect.element(page.getByText(/permanently removes 14 baselines/)).toBeVisible();
		await expect
			.element(page.getByRole('button', { name: 'Purge baselines', exact: true }))
			.toBeDisabled();
		await page.getByRole('textbox', { name: /PURGE BASELINES/ }).fill('PURGE BASELINES');
		await page.getByRole('button', { name: 'Purge baselines', exact: true }).click();

		expect(h.purge).toHaveBeenCalledWith(
			expect.objectContaining({
				impact_token: 'impact-token',
				expected_catalog_revision: 7,
				typed_confirmation: 'PURGE BASELINES'
			})
		);
	});
});
