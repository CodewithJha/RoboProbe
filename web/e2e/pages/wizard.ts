import type { Page } from '@playwright/test';

export function wizardPage(page: Page) {
  return {
    goto: () => page.goto('/campaigns/new'),
    heading: page.getByRole('heading', { name: 'New campaign', exact: true }),
    progress: page.getByRole('list', { name: 'Campaign setup progress' }),
    next: page.getByRole('button', { name: 'Continue', exact: true }),
    start: page.getByRole('button', { name: 'Create campaign', exact: true }),
  };
}
