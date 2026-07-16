import { createQuery } from '@tanstack/svelte-query';
import type { Getter } from 'runed';
import { api } from '$lib/api/client';
import { API } from '$lib/constants';
import { LibraryQueryKeyFactory } from './LibraryQueryKeyFactory';
import type {
	LibraryPathMappingReport,
	LibraryPolicyTreeResponse,
	TargetLibrarySettingsResponse
} from './LibraryOperationsTypes';

export const getTargetLibrarySettingsQuery = (enabled: Getter<boolean> = () => true) =>
	createQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryQueryKeyFactory.targetSettings(),
		queryFn: ({ signal }) =>
			api.global.get<TargetLibrarySettingsResponse>(API.library.settings(), { signal })
	}));

export const getLibraryPolicyTreeQuery = (enabled: Getter<boolean> = () => true) =>
	createQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryQueryKeyFactory.policyTree(),
		queryFn: ({ signal }) =>
			api.global.get<LibraryPolicyTreeResponse>(API.library.policyTree(), { signal })
	}));

export const getLibraryPathMappingQuery = (enabled: Getter<boolean> = () => false) =>
	createQuery(() => ({
		enabled: enabled(),
		queryKey: LibraryQueryKeyFactory.pathMapping(),
		queryFn: ({ signal }) =>
			api.global.get<LibraryPathMappingReport>(API.library.pathMapping(), { signal })
	}));
