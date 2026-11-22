import type { Page } from '@playwright/test';

export class CasebookPage {
  constructor(private readonly page: Page) {}

  async open(campaignId: string): Promise<void> {
    await this.page.goto(`/campaigns/${campaignId}/casebook`);
    await this.page.getByRole('heading', { name: 'Casebook' }).waitFor();
  }

  openMedoid(modeCode: string): Promise<void> {
    return this.page
      .getByRole('article')
      .filter({ hasText: modeCode })
      .getByRole('link', { name: 'Medoid run', exact: true })
      .click();
  }
}
