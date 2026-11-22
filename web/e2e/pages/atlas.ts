import type { Page } from '@playwright/test';

export function atlasPage(page: Page) {
  const selectedSlice = page.getByRole('region', { name: 'Selected risk slice' });
  return {
    goto: (campaignId: string) => page.goto(`/campaigns/${encodeURIComponent(campaignId)}/atlas`),
    heading: page.getByRole('heading', { name: 'Risk atlas', exact: true }),
    selectedSlice,
    riskDataTable: selectedSlice.getByText('Risk data table', { exact: true }),
    queueProbe: selectedSlice.getByRole('button', { name: 'Queue manual run', exact: true }),
  };
}
