import type { Page } from '@playwright/test';

export class CasebookPage {
  constructor(private readonly page: Page) {}

  async open(campaignId: string): Promise<void> {
    await this.page.goto(`/campaigns/${campaignId}/casebook`);
    await this.page.getByRole('heading', { name: 'Casebook' }).waitFor();
  }

  openMedoid(): Promise<void> {
    return this.page.getByRole('link', { name: 'Medoid run' }).first().click();
  }
}