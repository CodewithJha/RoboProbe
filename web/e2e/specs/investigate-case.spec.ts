import { expectNoA11yViolations } from '../a11y';
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
  await expect(page.getByRole('heading', { name: 'Exported report' })).toBeVisible({
    timeout: e2e.timeoutsMs.campaignRun,
  });
  const previewSelector = 'iframe[title="Report preview"]';
  await expectNoA11yViolations(page, { exclude: previewSelector });
  const preview = page.locator(previewSelector);
  await expect(preview).toHaveAttribute('sandbox', 'allow-same-origin allow-modals');
  await expect(
    preview.contentFrame().getByRole('heading', { name: 'Campaign report', exact: true }),
  ).toBeVisible();

  // Audit the same report document separately so axe can run without relaxing the preview sandbox.
  await expect(preview).toHaveAttribute('srcdoc', /default-src 'none'/);
  const html = await preview.getAttribute('srcdoc');
  const audit = await page.context().newPage();
  try {
    await audit.setContent(html ?? '');
    await expectNoA11yViolations(audit);
  } finally {
    await audit.close();
  }
});
