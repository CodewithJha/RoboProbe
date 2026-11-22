import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { delay, http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { type Campaign } from '../../api/hooks';
import { apiUrl, type Schema } from '../../api/client';
import { AppProviders } from '../../app/providers';
import { useQueryClient } from '@tanstack/react-query';
import { applyServerEvent } from '../../lib/sseBridge';
import { Component } from './ConsolePage';
import { CampaignHeader } from './header/CampaignHeader';

const fixture: Campaign = {
  id: 'c1',
  status: 'RUNNING',
  name: 'Night shift',
  strategy: { id: 'S-PROBE', seed: 42 },
  backend: 'kinematic2d',
  budget: 20,
  batch_size: 1,
  repeats: 1,
  modes_found: 0,
};
const run: Schema['RunOut'] = {
  id: 'r1',
  campaign_id: 'c1',
  ordinal: 1,
  repeat_index: 0,
  seed: 42,
  phase: 'mode_search',
  status: 'DONE',
  verdict: 'FAIL',
  primary_failure: 'F-COL',
  robustness: -0.34,
  scenario: {},
  proposal: {
    predicted_mean: -0.1,
    predicted_std: 0.21,
    acquisition_value: 0.4,
    nearest_case: { code: 'FM-03', distance: 0.12 },
  },
};
let campaign = fixture;
let runRows = [run];
let count = 1;
const server = setupServer(
  http.get(apiUrl('/campaigns/c1'), () => HttpResponse.json(campaign)),
  http.get(apiUrl('/campaigns/c1/progress'), () =>
    HttpResponse.json({
      campaign_id: 'c1',
      counts: { done: count, fail: count },
      discovery_curve: [{ run_ordinal: 1, unique_modes: 1 }],
    }),
  ),
  http.get(apiUrl('/campaigns/c1/runs'), () => HttpResponse.json({ items: runRows })),
);

beforeAll(() => {
  server.listen();
});
afterEach(() => {
  server.resetHandlers();
  campaign = fixture;
  runRows = [run];
  count = 1;
});
afterAll(() => {
  server.close();
});

function openConsole() {
  let queryClient: ReturnType<typeof useQueryClient> | undefined;
  function Capture() {
    queryClient = useQueryClient();
    return <Component />;
  }
  const router = createMemoryRouter(
    [
      { path: '/campaigns/:id/console', Component: Capture },
      { path: '/runs/:id', Component: () => <h1>Run detail</h1> },
    ],
    { initialEntries: ['/campaigns/c1/console'] },
  );
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return () => {
    if (!queryClient) throw new Error('Console has not mounted');
    return queryClient;
  };
}

it.each([
  ['CREATED', ['Start', 'Cancel campaign']],
  ['RUNNING', ['Pause', 'Cancel campaign']],
  ['PAUSED', ['Resume', 'Cancel campaign']],
  ['ANALYZING', []],
  ['COMPLETED', []],
  ['FAILED', []],
  ['CANCELLED', []],
] as const)('shows only allowed actions for %s', (status, actions) => {
  render(
    <AppProviders live={false}>
      <CampaignHeader campaign={{ ...fixture, status }} />
    </AppProviders>,
  );
  expect(
    within(screen.getByRole('banner'))
      .queryAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual(actions);
});

it('updates live counters and entries and shows a dismissible scoped alert', async () => {
  const getQueryClient = openConsole();
  expect(await screen.findByText('1 / 20 runs')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: 'Run #1' })).toBeInTheDocument();
  count = 2;
  runRows = [{ ...run, id: 'r2', ordinal: 2 }, run];
  act(() => {
    const client = getQueryClient();
    applyServerEvent(client, {
      type: 'run.finished',
      id: '1',
      data: { campaign_id: 'c1', run_id: 'r2' },
    });
    applyServerEvent(client, {
      type: 'alert',
      id: '2',
      data: { campaign_id: 'c1', code: 'INFRA_UNHEALTHY', message: 'Auto-paused' },
    });
  });
  expect(await screen.findByText('2 / 20 runs')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: 'Run #2' })).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Auto-paused');
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('waits for accepted commands and displays a conflict with refreshed status', async () => {
  server.use(
    http.post(/\/campaigns\/c1:pause$/, async () => {
      await delay(50);
      campaign = { ...fixture, status: 'PAUSED' };
      return HttpResponse.json(campaign, { status: 202 });
    }),
    http.post(/\/campaigns\/c1:resume$/, () => {
      campaign = { ...fixture, status: 'CANCELLED' };
      return HttpResponse.json(
        { title: 'Campaign conflict', detail: 'Already cancelled.' },
        { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
      );
    }),
  );
  openConsole();
  fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
  expect(await screen.findByText('Updating campaign…')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled();
  const resume = await screen.findByRole('button', { name: 'Resume' });
  await waitFor(() => {
    expect(resume).toBeEnabled();
  });
  fireEvent.click(resume);
  expect(await screen.findByText('Already cancelled.')).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument();
  });
});

it('virtualizes 10,000 entries and shows available rationale fields', async () => {
  runRows = Array.from({ length: 10_000 }, (_, index) => ({
    ...run,
    id: 'run-' + String(index),
    ordinal: 10_000 - index,
  }));
  openConsole();
  const stream = await screen.findByRole('region', { name: 'Newest campaign runs' });
  expect(within(stream).getAllByRole('link').length).toBeLessThan(100);
  expect(within(stream).getByText('Run #10000')).toBeInTheDocument();
  const first = within(stream).getAllByRole('article')[0];
  if (!first) throw new Error('Expected first run');
  expect(within(first).getByText('-0.10 ± 0.21')).toBeInTheDocument();
  expect(within(first).getByText('FM-03 · 0.12')).toBeInTheDocument();
  expect(within(first).queryByText('ε-explore')).not.toBeInTheDocument();
});
