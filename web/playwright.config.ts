import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env['E2E_BASE_URL'] ?? 'http://localhost:8080';
const ci = Boolean(process.env['CI']);

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  workers: 1,
  outputDir: './test-results/e2e',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    colorScheme: 'light',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
});
