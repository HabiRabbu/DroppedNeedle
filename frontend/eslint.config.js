import prettier from 'eslint-config-prettier';
import { fileURLToPath } from 'node:url';
import { includeIgnoreFile } from '@eslint/compat';
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

const gitignorePath = fileURLToPath(new URL('./.gitignore', import.meta.url));

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs.recommended,
	prettier,
	...svelte.configs.prettier,
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node }
		},
		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off',
			'@typescript-eslint/no-explicit-any': 'error',
			'@typescript-eslint/no-unused-vars': [
				'error',
				{ argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' }
			]
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig
			}
		},
		rules: {
			'svelte/no-navigation-without-resolve': 'off'
		}
	},
	{
		rules: {
			'no-restricted-syntax': [
				'error',
				// Ensure not to call queryClient.setQueriesData or queryClient.setQueryData directly, as this will bypass the persister and lead to data loss on page refresh.
				{
					selector:
						"CallExpression[callee.object.name='queryClient'][callee.property.name='setQueriesData']",
					message:
						"Direct use of 'queryClient.setQueriesData' is forbidden. Please use 'setQueryDataWithPersister' per matching query key instead (no plural helper exists)."
				},
				{
					selector:
						"CallExpression[callee.object.name='queryClient'][callee.property.name='setQueryData']",
					message:
						"Direct use of 'queryClient.setQueryData' is forbidden. Please use the 'setQueryDataWithPersister' function instead."
				},
				{
					selector:
						"CallExpression[callee.object.name='queryClient'][callee.property.name='invalidateQueries']",
					message:
						"Direct use of 'queryClient.invalidateQueries' is forbidden. Please use the custom 'invalidateQueriesWithPersister' hook instead."
				}
			]
		}
	}
);
