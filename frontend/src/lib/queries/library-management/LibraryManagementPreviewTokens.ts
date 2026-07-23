const TOKEN_PREFIX = 'droppedneedle:library-management:preview-token:';

export function rememberLibraryManagementPreviewToken(jobId: string, token: string): void {
	if (typeof sessionStorage === 'undefined') return;
	sessionStorage.setItem(`${TOKEN_PREFIX}${jobId}`, token);
}

export function readLibraryManagementPreviewToken(jobId: string): string | null {
	if (typeof sessionStorage === 'undefined') return null;
	return sessionStorage.getItem(`${TOKEN_PREFIX}${jobId}`);
}

export function forgetLibraryManagementPreviewToken(jobId: string): void {
	if (typeof sessionStorage === 'undefined') return;
	sessionStorage.removeItem(`${TOKEN_PREFIX}${jobId}`);
}
