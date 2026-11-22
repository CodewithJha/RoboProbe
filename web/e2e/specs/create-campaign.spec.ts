import { BenchPage } from '../pages/bench';
import { ConsolePage } from '../pages/console';
import { WizardPage } from '../pages/wizard';
import { afterNavigation, e2e, test, expect } from '../fixtures';

test('wizard creates a k2d campaign and console streams runs', async ({ page }) => {
  const bench = new BenchPage(page);
  const wizard = new WizardPage(page, e2e.wizard);
  const console = new ConsolePage(page);

  await bench.open();
  await afterNavigation(page);
  await bench.newCampaign();
  await afterNavigation(page);

  const campaignId = await wizard.createK2dCampaign();
  await console.open(campaignId);
  await afterNavigation(page);

  const started = Date.now();
  await console.waitForFinishedRuns(1, e2e.timeoutsMs.campaignRun);
  expect(Date.now() - started).toBeLessThan(e2e.timeoutsMs.campaignRun);
});
