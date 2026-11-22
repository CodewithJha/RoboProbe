import { AtlasPage } from '../pages/atlas';
import { afterNavigation, e2e, expect, test } from '../fixtures';

test('risk atlas probe-here enqueues a manual run', async ({ page }) => {
  const atlas = new AtlasPage(page);
  await atlas.open(e2e.seed.campaignId);
  await afterNavigation(page);
  await atlas.probeFromTable();
  await expect(page.getByText(/Manual run queued/)).toBeVisible();
  await afterNavigation(page);
});