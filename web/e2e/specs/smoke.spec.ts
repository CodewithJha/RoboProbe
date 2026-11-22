import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '../fixtures';
import { seed } from '../seed';

test('renders the seeded Bench and opens its campaign console', async ({ page }) => {
  const response = await page.goto('/');
  expect(response?.headers()['content-security-policy']).toContain("default-src 'self'");
  await expect(page.getByRole('heading', { name: 'Bench', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'New campaign', exact: true })).toBeVisible();
  const campaign = page
    .getByRole('table', { name: 'Recent campaigns' })
    .getByRole('link', { name: seed.campaign.name, exact: true });
  await expect(campaign).toBeVisible();
  const cases = seed.campaignModes.map((mode) =>
    expect(page.getByRole('link', { name: new RegExp(mode.code) })).toBeVisible(),
  );
  await Promise.all(cases);

  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(
    violations.filter(({ impact }) => impact === 'serious' || impact === 'critical'),
    'serious or critical Bench accessibility violations',
  ).toEqual([]);

  await campaign.press('Enter');
  await expect(page.getByRole('heading', { name: seed.campaign.name, exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/campaigns/${seed.campaign.id}/console$`));
});
