import { afterNavigation, e2e, test, expect } from '../fixtures';

test('experiment comparison lists every strategy', async ({ page }) => {
  await page.goto(`/trials/${e2e.seed.experimentId}/comparison`);
  await page.getByRole('heading', { name: 'Compare strategies' }).waitFor();
  await afterNavigation(page);
  await expect(page.getByText('S-RANDOM')).toBeVisible();
});