import { BenchPage } from '../pages/bench';
import { afterNavigation, expect, test } from '../fixtures';

test('bench renders with axe clean', async ({ page }) => {
  const bench = new BenchPage(page);
  await bench.open();
  await expect(page.getByRole('heading', { name: 'Bench' })).toBeVisible();
  await afterNavigation(page);
});
