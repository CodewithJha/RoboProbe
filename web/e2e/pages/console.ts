import type { Page } from '@playwright/test';

export function consolePage(page: Page) {
  const runs = page.getByRole('region', { name: 'Newest campaign runs' });
  return {
    goto: (campaignId: string) => page.goto(`/campaigns/${encodeURIComponent(campaignId)}/console`),
    heading: (name: string) => page.getByRole('heading', { name, exact: true }),
    run: (ordinal: number) =>
      runs.getByRole('link', { name: `Run #${String(ordinal)}`, exact: true }),
    pause: page.getByRole('button', { name: 'Pause', exact: true }),
    resume: page.getByRole('button', { name: 'Resume', exact: true }),
  };
}
