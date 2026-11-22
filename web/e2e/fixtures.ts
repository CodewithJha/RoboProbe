import { expect, test as base } from '@playwright/test';
import { atlasPage } from './pages/atlas';
import { benchPage } from './pages/bench';
import { casebookPage } from './pages/casebook';
import { consolePage } from './pages/console';
import { runPage } from './pages/run';
import { wizardPage } from './pages/wizard';

interface Pages {
  atlas: ReturnType<typeof atlasPage>;
  bench: ReturnType<typeof benchPage>;
  casebook: ReturnType<typeof casebookPage>;
  console: ReturnType<typeof consolePage>;
  runEntry: ReturnType<typeof runPage>;
  wizard: ReturnType<typeof wizardPage>;
}

export const test = base.extend<Pages>({
  page: async ({ page, baseURL }, provide) => {
    const token = process.env['E2E_API_TOKEN'];
    if (!baseURL || !token) throw new Error('The Compose setup did not supply an E2E API session.');
    await page.addInitScript(
      ({ origin, bearer }) => {
        if (location.origin === origin) sessionStorage.setItem('roboprobe.api-token', bearer);
      },
      { origin: new URL(baseURL).origin, bearer: token },
    );
    await provide(page);
  },
  atlas: async ({ page }, provide) => {
    await provide(atlasPage(page));
  },
  bench: async ({ page }, provide) => {
    await provide(benchPage(page));
  },
  casebook: async ({ page }, provide) => {
    await provide(casebookPage(page));
  },
  console: async ({ page }, provide) => {
    await provide(consolePage(page));
  },
  runEntry: async ({ page }, provide) => {
    await provide(runPage(page));
  },
  wizard: async ({ page }, provide) => {
    await provide(wizardPage(page));
  },
});

export { expect };
