import { afterNavigation, test, expect } from '../fixtures';
import { seed } from '../seed';

test('experiment comparison lists every strategy', async ({ page }) => {
  await page.goto(`/trials/${seed.experimentId}/comparison`);
  await page.getByRole('heading', { name: 'Compare strategies' }).waitFor();
  await afterNavigation(page);
  const metrics = page.getByRole('table', { name: 'Strategy metrics' });
  await Promise.all(
    seed.strategies.map((name) =>
      expect(metrics.getByRole('cell', { name, exact: true }).first()).toBeVisible(),
    ),
  );
});
