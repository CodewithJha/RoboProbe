import { afterNavigation, e2e, expect, test } from '../fixtures';

async function setTheme(page: import('@playwright/test').Page, theme: 'light' | 'dark'): Promise<void> {
  await page.goto('/settings');
  await page.locator('#theme').selectOption(theme);
}

async function tabThrough(page: import('@playwright/test').Page): Promise<void> {
  for (let i = 0; i < 12; i += 1) {
    await page.keyboard.press('Tab');
    const active = page.locator(':focus');
    await expect(active).toBeVisible();
  }
}

test.describe('light theme route sweep', () => {
  for (const route of e2e.routes) {
    test(`axe + keyboard on ${route}`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator('h1').first()).toBeVisible({ timeout: e2e.timeoutsMs.navigation });
      await afterNavigation(page);
      await tabThrough(page);
    });
  }
});

test.describe('dark theme route sweep', () => {
  test.beforeEach(async ({ page }) => {
    await setTheme(page, 'dark');
  });

  for (const route of e2e.routes) {
    test(`axe + keyboard on ${route}`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator('h1').first()).toBeVisible({ timeout: e2e.timeoutsMs.navigation });
      await afterNavigation(page);
      await tabThrough(page);
    });
  }
});