// Test stub for `$env/dynamic/public`: the real virtual module crashes on import in the chromium vitest env (no SSR request to inject the public env global). Empty env (PUBLIC_API_URL undefined -> relative URLs) matches no configured base URL. Wired in vite.config.ts.
export const env: Record<string, string> = {};
