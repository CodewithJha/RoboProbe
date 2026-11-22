import axe from 'axe-core';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { apiUrl } from '../../api/client';
import { AppProviders } from '../../app/providers';
import campaigns from '../../test/fixtures/campaigns.json';
import modes from '../../test/fixtures/modes.json';
import { Component } from './BenchPage';

const campaign = campaigns.items[0];
if (!campaign) throw new Error('The test seed must contain a campaign');

const empty = { items: [] };
const server = setupServer(
  http.get(apiUrl('/campaigns'), ({ request }) =>
    HttpResponse.json(new URL(request.url).searchParams.has('status') ? empty : campaigns),
  ),
  http.get(apiUrl(`/campaigns/${campaign.id}/modes`), () => HttpResponse.json(modes)),
  http.get(apiUrl('/workers'), () => HttpResponse.json(empty)),
  http.get(apiUrl('/meta'), () => HttpResponse.json({})),
);

beforeAll(() => {
  server.listen();
});
afterEach(() => {
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});

function renderBench() {
  return render(
    <AppProviders live={false}>
      <MemoryRouter>
        <main>
          <Component />
        </main>
      </MemoryRouter>
    </AppProviders>,
  );
}

it('renders the seeded campaign, all three modes and a focusable campaign link', async () => {
  const { container } = renderBench();
  const table = await screen.findByRole('table', { name: 'Recent campaigns' });
  const link = within(table).getByRole('link', { name: campaign.name });
  link.focus();
  expect(link).toHaveFocus();
  expect(link).toHaveAttribute('href', `/campaigns/${campaign.id}/console`);
  expect(within(table).getByText('60 / 36')).toBeInTheDocument();
  for (const mode of modes.items) {
    expect(await screen.findByRole('link', { name: new RegExp(mode.code) })).toHaveAttribute(
      'href',
      `/campaigns/${campaign.id}/casebook`,
    );
  }
  const results = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
  expect(
    results.violations.filter((item) => ['critical', 'serious'].includes(item.impact ?? '')),
  ).toEqual([]);
});

it('keeps the loading state accessible and displays the empty state when the query resolves', async () => {
  let resolve: () => void = () => {
    throw new Error('Campaign query resolver is not available');
  };
  const pending = new Promise<void>((resolveRequest) => {
    resolve = resolveRequest;
  });
  server.use(
    http.get(apiUrl('/campaigns'), async () => {
      await pending;
      return HttpResponse.json(empty);
    }),
  );
  renderBench();
  const status = await screen.findByText('Opening your campaigns…');
  expect(status.closest('[aria-busy="true"]')).toBeInTheDocument();
  resolve();
  expect(await screen.findByRole('heading', { name: 'No campaigns yet' })).toBeInTheDocument();
  expect(status).not.toBeInTheDocument();
});

it('displays the API error with the standard problem view', async () => {
  server.use(
    http.get(apiUrl('/campaigns'), () =>
      HttpResponse.json(
        { title: 'Request forbidden', detail: 'The notebook could not be opened.' },
        { status: 403 },
      ),
    ),
  );
  renderBench();
  const alert = await screen.findByRole('alert');
  expect(within(alert).getByRole('heading', { name: 'Request forbidden' })).toBeInTheDocument();
  expect(within(alert).getByRole('link', { name: 'Return to Bench' })).toBeInTheDocument();
});
