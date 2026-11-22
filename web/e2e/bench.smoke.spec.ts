import { expectNoA11yViolations } from './a11y';
import { expect, test } from './fixtures';
import { seed } from './seed';

test('renders the seeded Bench and opens its campaign console', async ({
  bench,
  console: campaignConsole,
  page,
}) => {
  const runtimeErrors: string[] = [];
  const policyErrors: string[] = [];
  page.on('pageerror', (error) => runtimeErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && /content.security.policy|CSP/i.test(message.text())) {
      policyErrors.push(message.text());
    }
  });
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (event) => {
      console.error(`CSP violation: ${event.effectiveDirective} blocked ${event.blockedURI}`);
    });
  });
  const response = await bench.goto();
  expect(response?.headers()['content-security-policy']).toContain("default-src 'self'");
  await expect(bench.heading).toBeVisible();
  await expect(bench.newCampaign).toBeVisible();
  const campaign = bench.campaign(seed.campaign.name);
  await expect(campaign).toBeVisible();
  for (const mode of seed.campaignModes) await expect(bench.caseTag(mode.code)).toBeVisible();
  await expectNoA11yViolations(page);

  await campaign.focus();
  await page.keyboard.press('Enter');
  await expect(campaignConsole.heading(seed.campaign.name)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/campaigns/${seed.campaign.id}/console$`));
  expect(runtimeErrors).toEqual([]);
  expect(policyErrors).toEqual([]);
});
