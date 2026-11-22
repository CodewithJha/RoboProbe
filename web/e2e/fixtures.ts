import { test as base, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { expectNoA11yViolations } from './a11y';
import config from './e2e.config.json';

function guardConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    errors.push(error.message);
  });
  return errors;
}

const E2E_API_TOKEN = process.env['E2E_API_TOKEN'] ?? 'e2e-ci-token';

export const test = base.extend<{ consoleErrors: string[] }>({
  page: async ({ page }, use) => {
    await page.addInitScript((token) => {
      sessionStorage.setItem('roboprobe.api-token', token);
    }, E2E_API_TOKEN);
    await use(page);
  },
  consoleErrors: [
    async ({ page }, use) => {
      const errors = guardConsole(page);
      await use(errors);
      expect(errors, 'browser console errors').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export async function afterNavigation(page: Page): Promise<void> {
  await expectNoA11yViolations(page);
}

export const e2e = config;
