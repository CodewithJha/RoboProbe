import { CasebookPage } from '../pages/casebook';
import { afterNavigation, e2e, test, expect } from '../fixtures';
import { seed } from '../seed';

test('casebook medoid → replay ×3 → export report', async ({ page }) => {
  const casebook = new CasebookPage(page);
  await casebook.open(seed.campaign.id);
  await afterNavigation(page);
  await casebook.openMedoid(seed.medoid.modeCode);
  await afterNavigation(page);

  await expect(page).toHaveURL(new RegExp(`/runs/${seed.medoid.id}$`));
  await page.getByRole('button', { name: 'Replay' }).click();
  await page.getByLabel('Repeats').fill(String(e2e.replayRepeats));
  await page.getByRole('button', { name: 'Queue replay' }).click();
  await page.waitForURL(/\/campaigns\/[^/]+\/console/);
  await page.getByRole('button', { name: 'Export report' }).click();
  await page.waitForURL(/\/reports\//);
  await afterNavigation(page);
  await expect(page.getByRole('heading', { name: 'Exported report' })).toBeVisible({
    timeout: e2e.timeoutsMs.campaignRun,
  });
  const preview = page.frameLocator('iframe[title="Report preview"]');
  await expect(preview.getByRole('heading', { name: 'Campaign report', exact: true })).toBeVisible();
});
