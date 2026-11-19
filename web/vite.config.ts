/**
 * Vite + Vitest configuration for the RoboProbe dashboard.
 *
 * Application code never hard-codes URLs: the API base path and the dev-server proxy target are
 * read from the environment (`web/.env.example` documents every key; doc 27 §4.11).
 */
import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

/** Documented defaults, applied only when the corresponding env var is unset or blank. */
const ENV_DEFAULTS = {
  VITE_API_BASE_URL: '/api/v1',
  VITE_API_PROXY_TARGET: 'http://127.0.0.1:8000',
} as const;

/** Path prefix the dev server forwards to the backend (matches the API mount in doc 12). */
const API_PROXY_PATH = '/api';

/** Minimum web line coverage required by the quality gate (doc 18 §3). */
const COVERAGE_THRESHOLD_PERCENT = 70;

function envOrDefault(env: Record<string, string>, key: keyof typeof ENV_DEFAULTS): string {
  const value = env[key]?.trim();
  return value === undefined || value === '' ? ENV_DEFAULTS[key] : value;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');

  return {
    plugins: [react()],
    define: {
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(envOrDefault(env, 'VITE_API_BASE_URL')),
    },
    server: {
      proxy: {
        [API_PROXY_PATH]: {
          target: envOrDefault(env, 'VITE_API_PROXY_TARGET'),
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx', 'src/vite-env.d.ts'],
        thresholds: { lines: COVERAGE_THRESHOLD_PERCENT },
      },
    },
  };
});
