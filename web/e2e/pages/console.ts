import type { Page } from '@playwright/test';

export class ConsolePage {
  constructor(private readonly page: Page) {}

  async open(campaignId: string): Promise<void> {
    await this.page.goto(`/campaigns/${campaignId}/console`);
    await this.page.getByRole('region', { name: 'Newest campaign runs' }).waitFor();
  }

  async waitForFinishedRuns(minimum: number, timeoutMs: number): Promise<void> {
    const region = this.page.getByRole('region', { name: 'Newest campaign runs' });
    await region
      .locator('a[href^="/runs/"]')
      .nth(minimum - 1)
      .waitFor({ timeout: timeoutMs });
  }

  pause(): Promise<void> {
    return this.page.getByRole('button', { name: 'Pause' }).click();
  }

  resume(): Promise<void> {
    return this.page.getByRole('button', { name: 'Resume' }).click();
  }

  cancel(): Promise<void> {
    return this.page.getByRole('button', { name: 'Cancel campaign' }).click();
  }
}
