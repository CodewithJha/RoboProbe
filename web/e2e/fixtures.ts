import { test as base, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { expectNoA11yViolations } from './a11y';
import config from './e2e.config.json' with { type: 'json' };

const sandboxedReportProbe =
  "Blocked script execution in 'about:srcdoc' because the document's frame is sandboxed and the 'allow-scripts' permission is not set.";

function guardConsole(page: Page, inspectSandboxedReport: boolean): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (inspectSandboxedReport && text === sandboxedReportProbe) return;
    errors.push(text);
  });
  page.on('pageerror', (error) => {
    errors.push(error.message);
  });
  return errors;
}

export const test = base.extend<{ consoleErrors: string[]; inspectSandboxedReport: boolean }>({
  inspectSandboxedReport: [false, { option: true }],
  page: async ({ page, baseURL }, provide) => {
    const token = process.env['E2E_API_TOKEN'];
    if (!baseURL || !token) throw new Error('The Compose setup did not supply an E2E API session.');
    const config = await page.goto(new URL('/config.json', baseURL).href);
    expect(config?.ok(), 'same-origin runtime config').toBe(true);
    await page.evaluate((bearer) => {
      sessionStorage.setItem('roboprobe.api-token', bearer);
    }, token);
    await provide(page);
  },
  consoleErrors: [
    async ({ page, inspectSandboxedReport }, use) => {
      const errors = guardConsole(page, inspectSandboxedReport);
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
