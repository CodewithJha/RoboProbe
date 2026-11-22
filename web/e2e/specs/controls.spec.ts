import { ConsolePage } from '../pages/console';
import { WizardPage } from '../pages/wizard';
import { afterNavigation, e2e, test, expect } from '../fixtures';

test('campaign pause resume cancel transitions', async ({ page }) => {
  const wizard = new WizardPage(page, { ...e2e.wizard, budget: 6 });
  const console = new ConsolePage(page);

  await wizard.open();
  const campaignId = await wizard.createK2dCampaign();
  await console.open(campaignId);
  await afterNavigation(page);

  await console.pause();
  await expect(page.getByRole('button', { name: 'Pause' })).toBeDisabled();
  await console.resume();
  await expect(page.getByRole('button', { name: 'Resume' })).toBeDisabled();
  await console.cancel();
  await page.getByRole('button', { name: 'Confirm cancellation' }).click();
  await expect(page.getByText(/· CANCELLED$/)).toBeVisible();
});
