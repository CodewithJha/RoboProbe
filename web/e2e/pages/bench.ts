import type { Page } from '@playwright/test';

export class BenchPage {
  constructor(private readonly page: Page) {}

  async open(): Promise<void> {
    await this.page.goto('/');
    await this.page.getByRole('heading', { name: 'Bench' }).waitFor();
  }

  newCampaign(): Promise<void> {
    return this.page.getByRole('link', { name: 'New campaign' }).click();
  }
}