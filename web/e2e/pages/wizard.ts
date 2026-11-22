import type { Page } from '@playwright/test';
import type e2eConfig from '../e2e.config.json';

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
    await this.page
      .getByLabel(/Scenario space/)
      .selectOption({ label: 'warehouse_v1 · 09cf763f2e0d' });
    await this.page.getByRole('button', { name: 'Continue' }).click();
    await this.page.getByLabel('Backend').selectOption('kinematic2d');
    await this.page.getByLabel('Robot profile').selectOption('k2d_default');
    await this.page.getByRole('button', { name: 'Continue' }).click();
    await this.page.getByRole('radio', { name: /S-RANDOM/ }).check();
    await this.page.getByLabel('Budget').fill(String(this.settings.budget));
    await this.page.getByLabel('Batch size').fill(String(this.settings.batchSize));
    await this.page.getByLabel('Seed').fill(String(this.settings.seed));
    await this.page.getByRole('button', { name: 'Continue' }).click();
    await this.page.getByRole('button', { name: 'Create campaign' }).click();
    await this.page.waitForURL(/\/campaigns\/[^/]+\/console/);
    const matched = /\/campaigns\/([^/]+)\//.exec(this.page.url());
    if (!matched?.[1]) throw new Error('expected to land on a campaign console URL');
    return matched[1];
  }
}
