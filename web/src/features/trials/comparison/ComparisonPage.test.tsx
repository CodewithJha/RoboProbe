import { fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { apiUrl } from '../../../api/client';
import { AppProviders } from '../../../app/providers';
import { Component as ExperimentPage } from '../ExperimentPage';
import { Component as TrialsPage } from '../TrialsPage';
import { Component } from './ComparisonPage';

const experiment = {
  id: 'e1',
  name: 'Warehouse sweep',
  status: 'COMPLETED',
  version: 1,
  notes: 'Initial note',
  design: { strategies: [{ id: 'S-PROBE' }] },
  cells: [
    { campaign_id: 'c1', strategy_id: 'S-PROBE', seed: 13, budget: 100, status: 'COMPLETED' },
  ],
};
const patch = vi.fn();
const server = setupServer(
  http.get(apiUrl('/experiments'), () =>
    HttpResponse.json({
      items: [{ ...experiment, cells: [], progress: { completed: 2, total: 3 } }],
    }),
  ),
  http.get(apiUrl('/experiments/e1'), () =>
    HttpResponse.json(experiment, { headers: { ETag: 'W/"1"' } }),
  ),
  http.get(apiUrl('/experiments/e1/comparison'), () =>
    HttpResponse.json({
      experiment_id: 'e1',
      metrics: ['MET-01', 'MET-03'],
      strategies: {
        'S-RANDOM': { 'MET-01': { median: 0.5, iqr: [0.4, 0.6] }, 'MET-03': { median: 50 } },
        'S-PROBE': { 'MET-01': { median: 0.7, iqr: [0.6, 0.8] }, 'MET-03': { median: 30 } },
      },
      tests: [
        {
          metric: 'MET-01',
          a: 'S-PROBE',
          b: 'S-RANDOM',
          test: 'mann_whitney_u',
          p: 0.03,
          p_holm: 0.06,
          a12: 0.7,
          effect: 'medium',
        },
      ],
    }),
  ),
  http.patch(apiUrl('/experiments/e1'), async ({ request }) => {
    const body = await request.json();
    patch(request.headers.get('If-Match'), body);
    return HttpResponse.json(
      { ...experiment, notes: 'Saved from the bench', version: 2 },
      { headers: { ETag: 'W/"2"' } },
    );
  }),
);
beforeAll(() => {
  server.listen();
});
afterAll(() => {
  server.close();
});
afterEach(() => {
  server.resetHandlers();
});
function mount(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/trials', Component: TrialsPage },
      { path: '/trials/:id', Component: ExperimentPage },
      { path: '/trials/:id/comparison', Component },
    ],
    { initialEntries: [path] },
  );
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

it('links an experiment design cell to its child campaign', async () => {
  mount('/trials/e1');
  const cell = await screen.findByRole('link', { name: 'Open S-PROBE campaign (seed 13)' });
  expect(cell).toHaveAttribute('href', '/campaigns/c1/console');
});

it('shows index progress without loading each experiment detail', async () => {
  mount('/trials');
  const link = await screen.findByRole('link', { name: 'Warehouse sweep' });
  expect(link).toHaveAttribute('href', '/trials/e1');
  expect(screen.getByRole('cell', { name: '2 / 3' })).toBeInTheDocument();
});

it('renders every strategy and metric and saves notes with the GET version', async () => {
  mount('/trials/e1/comparison');
  const metrics = await screen.findByRole('table', { name: 'Strategy metrics' });
  expect(within(metrics).getAllByRole('row')).toHaveLength(5);
  fireEvent.click(within(metrics).getByRole('button', { name: 'Median' }));
  expect(within(metrics).getAllByRole('row')[1]).toHaveTextContent('S-RANDOM');
  expect(screen.getByText('medium')).toBeInTheDocument();
  fireEvent.change(await screen.findByRole('textbox', { name: 'Experiment notes' }), {
    target: { value: 'Saved from the bench' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save notes' }));
  expect(await screen.findByText('Notes saved.')).toBeInTheDocument();
  expect(patch).toHaveBeenCalledWith('W/"1"', { notes: 'Saved from the bench' });
});

it('keeps the draft when the notes version changes and requires an explicit retry', async () => {
  let changed = false;
  server.use(
    http.get(apiUrl('/experiments/e1'), () =>
      HttpResponse.json(changed ? { ...experiment, notes: 'Saved by collaborator' } : experiment, {
        headers: { ETag: changed ? 'W/"2"' : 'W/"1"' },
      }),
    ),
    http.patch(apiUrl('/experiments/e1'), () => {
      changed = true;
      return HttpResponse.json({ detail: 'Version changed' }, { status: 412 });
    }),
  );
  mount('/trials/e1/comparison');
  const editor = await screen.findByRole('textbox', { name: 'Experiment notes' });
  fireEvent.change(editor, { target: { value: 'My draft' } });
  const save = screen.getByRole('button', { name: 'Save notes' });
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent(/someone saved a newer version/i);
  expect(editor).toHaveValue('My draft');
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Load latest notes' }));
  expect(await screen.findByText('Saved by collaborator')).toBeInTheDocument();
  expect(save).toBeEnabled();
  expect(editor).toHaveValue('My draft');
});
