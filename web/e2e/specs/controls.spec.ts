import { ConsolePage } from '../pages/console';
import { WizardPage } from '../pages/wizard';
import { afterNavigation, e2e, test, expect } from '../fixtures';

test('campaign pause resume cancel transitions', async ({ page }) => {
  const wizard = new WizardPage(page, { ...e2e.wizard, budget: e2e.controlBudget });
  const console = new ConsolePage(page);

  await wizard.open();
  const campaignId = await wizard.createK2dCampaign();
  await console.open(campaignId);
  await afterNavigation(page);

  await console.pause();
  await expect(page.getByText(/· PAUSED$/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Pause' })).toHaveCount(0);
  await console.resume();
  await expect(page.getByText(/· RUNNING$/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Resume' })).toHaveCount(0);
  await console.cancel();
  await page.getByRole('button', { name: 'Confirm cancellation' }).click();
  await expect(page.getByText(/· CANCELLED$/)).toBeVisible();
});
