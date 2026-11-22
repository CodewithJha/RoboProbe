import type { Page } from '@playwright/test';

export class AtlasPage {
  constructor(private readonly page: Page) {}

  async open(campaignId: string): Promise<void> {
    await this.page.goto(`/campaigns/${campaignId}/atlas`);
    await this.page.getByRole('heading', { name: 'Risk atlas' }).waitFor();
  }

  async probeFromTable(): Promise<void> {
    await this.page.getByText('Risk data table').click();
    const cell = this.page.getByRole('button').filter({ hasText: /\d/ }).first();
    await cell.click();
    await this.page.getByRole('button', { name: 'Queue manual run' }).click();
    await this.page.getByText(/Manual run queued/).waitFor({ timeout: 30_000 });
  }
}