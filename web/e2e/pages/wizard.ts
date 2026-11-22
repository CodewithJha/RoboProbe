import type { Page } from '@playwright/test';
import type e2eConfig from '../e2e.config.json';
import { seed } from '../seed';

export class WizardPage {
  constructor(
    private readonly page: Page,
    private readonly settings: (typeof e2eConfig)['wizard'],
  ) {}

  async open(): Promise<void> {
    await this.page.goto('/campaigns/new');
    await this.page.getByRole('heading', { name: 'New campaign' }).waitFor();
  }

  async createK2dCampaign(): Promise<string> {
    const { id } = seed.campaign.space;
    const version = process.env['E2E_WIZARD_SPACE_VERSION'];
    if (!version) throw new Error('The Compose setup did not register the Wizard space.');
    await this.page.getByLabel(/Scenario space/).selectOption(JSON.stringify([id, version]));
    await this.page
      .getByRole('status')
      .filter({ hasText: /\d+ free parameters/ })
      .waitFor();
    await this.page.getByRole('button', { name: 'Continue' }).click();
    await this.page.getByLabel('Backend').selectOption('kinematic2d');
    await this.page.getByLabel('Robot profile').selectOption('k2d_default');
    await this.page.getByRole('button', { name: 'Continue' }).click();
    await this.page.getByRole('radio', { name: /S-RANDOM/ }).check();
    await this.page.getByLabel('Budget').fill(String(this.settings.budget));
    await this.page.getByLabel('Batch size').fill(String(this.settings.batchSize));
    await this.page.getByLabel('Seed').fill(String(this.settings.seed));
    await this.page.getByRole('button', { name: 'Continue' }).click();
    const [created] = await Promise.all([
      this.page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname === '/api/v1/campaigns',
      ),
      this.page.getByRole('button', { name: 'Create campaign' }).click(),
    ]);
    if (created.status() !== 201)
      throw new Error(`Creating a campaign returned ${String(created.status())}.`);
    await this.page.waitForURL(/\/campaigns\/[^/]+\/console/);
    const matched = /\/campaigns\/([^/]+)\//.exec(this.page.url());
    if (!matched?.[1]) throw new Error('expected to land on a campaign console URL');
    return matched[1];
  }
}
