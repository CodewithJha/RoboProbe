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

export const test = base.extend<{ consoleErrors: string[] }>({
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