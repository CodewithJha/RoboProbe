import type { Page } from '@playwright/test';

export function benchPage(page: Page) {
  return {
    goto: () => page.goto('/'),
    heading: page.getByRole('heading', { name: 'Bench', exact: true }),
    newCampaign: page.getByRole('link', { name: 'New campaign', exact: true }),
    campaign: (name: string) =>
      page
        .getByRole('table', { name: 'Recent campaigns' })
        .getByRole('link', { name, exact: true }),
    caseTag: (code: string) => page.getByRole('link', { name: new RegExp(code) }),
  };
}
