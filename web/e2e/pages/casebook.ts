import type { Page } from '@playwright/test';

export function casebookPage(page: Page) {
  return {
    goto: (campaignId: string) =>
      page.goto(`/campaigns/${encodeURIComponent(campaignId)}/casebook`),
    heading: page.getByRole('heading', { name: 'Casebook', exact: true }),
    mode: (code: string) => page.getByText(code, { exact: true }),
  };
}
