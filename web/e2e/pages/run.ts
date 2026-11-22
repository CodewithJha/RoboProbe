import type { Page } from '@playwright/test';

export function runPage(page: Page) {
  return {
    goto: (runId: string) => page.goto(`/runs/${encodeURIComponent(runId)}`),
    heading: page.getByRole('heading', { name: 'Run entry', exact: true }),
    replay: page.getByRole('button', { name: 'Replay', exact: true }),
    provenance: page.getByRole('button', { name: 'Provenance', exact: true }),
  };
}
