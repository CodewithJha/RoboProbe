import { fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { apiUrl } from '../../../api/client';
import { AppProviders } from '../../../app/providers';
import { DEFAULT_CONFIG, type RuntimeConfig } from '../../../lib/config';
import { setToken } from '../../../lib/token';
import { Component as ExperimentPage } from '../ExperimentPage';
import { Component as TrialsPage } from '../TrialsPage';
import { Component as ComparisonPageComponent } from './ComparisonPage';
import { Component as ReportPage } from '../../reports/ReportPage';

const plot = vi.hoisted(() => vi.fn<(props: { data: object[] }) => null>(() => null));
vi.mock('../../../components/charts/plotly', () => ({
  loadPlotly: () => Promise.resolve({ default: plot }),
}));

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
  http.get(apiUrl('/experiments/e1/comparison/charts'), () =>
    HttpResponse.json({
      experiment_id: 'e1',
      metrics: ['MET-01', 'MET-03'],
      confidence: 0.95,
      excluded_cells: 1,
      groups: [
        {
          strategy: 'S-PROBE',
          observed_cells: 2,
          analyzed_cells: 2,
          metric_samples: { 'MET-01': [0.4, 0.8], 'MET-03': [3] },
          discovery: [
            { simulations: 0, median: 0, low: 0, high: 0 },
            { simulations: 4, median: 1, low: 0, high: 2 },
          ],
          survival: [
            { simulations: 0, probability: 1, censored: 0 },
            { simulations: 3, probability: 0.5, censored: 0 },
            { simulations: 6, probability: 0.5, censored: 1 },
          ],
        },
        {
          strategy: 'S-RANDOM',
          observed_cells: 1,
          analyzed_cells: 0,
          metric_samples: { 'MET-01': [0], 'MET-03': [] },
          discovery: [],
          survival: [
            { simulations: 0, probability: 1, censored: 0 },
            { simulations: 6, probability: 1, censored: 1 },
          ],
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
function mount(path: string, config: RuntimeConfig = DEFAULT_CONFIG) {
  const router = createMemoryRouter(
    [
      { path: '/trials', Component: TrialsPage },
      { path: '/trials/:id', Component: ExperimentPage },
      { path: '/trials/:id/comparison', Component: ComparisonPageComponent },
      { path: '/reports/:id', Component: ReportPage },
    ],
    { initialEntries: [path] },
  );
  render(
    <AppProviders live={false} config={config}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
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

it('plots empirical samples, mode bands and right-censored survival for completed cells', async () => {
  mount('/trials/e1/comparison');
  const charts = await screen.findByRole('region', { name: 'Comparison charts' });
  const evidence = within(charts);
  expect(await evidence.findByRole('region', { name: 'Mode discovery' })).toBeInTheDocument();
  expect(
    evidence.getByRole('region', { name: 'Time to first failure (MET-03)' }),
  ).toBeInTheDocument();
  expect(evidence.getByRole('region', { name: 'MET-01 per-cell samples' })).toBeInTheDocument();
  expect(evidence.getByRole('region', { name: 'MET-03 per-cell samples' })).toBeInTheDocument();
  const traces = plot.mock.calls.flatMap(([props]) => props.data);
  expect(traces).toContainEqual(expect.objectContaining({ x: [0, 4], y: [0, 0] }));
  expect(traces).toContainEqual(expect.objectContaining({ fill: 'tonexty', x: [0, 4], y: [0, 2] }));
  expect(traces).toContainEqual(expect.objectContaining({ name: 'S-PROBE', x: [0, 4], y: [0, 1] }));
  expect(traces).toContainEqual(
    expect.objectContaining({
      mode: 'markers',
      x: [6],
      y: [1],
      text: ['S-RANDOM, 1 censored at 6 simulations'],
    }),
  );
  expect(traces).toContainEqual(expect.objectContaining({ type: 'box', name: 'S-PROBE', x: [3] }));
  expect(evidence.getByText('No observed values for S-RANDOM.')).toBeInTheDocument();
  expect(evidence.getByText('1 cell lacks completed run evidence.')).toBeInTheDocument();
});

it('generates a report, polls until complete, and opens the report view', async () => {
  const authored = vi.fn();
  let reads = 0;
  let completed = false;
  const job = { id: 'r1', kind: 'experiment', target_id: 'e1' };
  server.use(
    http.post(apiUrl('/reports'), async ({ request }) => {
      authored(request.headers.get('Authorization'), await request.json());
      return HttpResponse.json({ ...job, status: 'RUNNING' }, { status: 202 });
    }),
    http.get(apiUrl('/reports/r1'), () => {
      reads += 1;
      return HttpResponse.json({ ...job, status: completed ? 'COMPLETED' : 'RUNNING' });
    }),
    http.get(apiUrl('/reports/r1/content'), ({ request }) => {
      expect(request.headers.get('Authorization')).toBe('Bearer test-report-token');
      return HttpResponse.html('<h1>Experiment report</h1>');
    }),
  );
  setToken('test-report-token');
  try {
    const view = mount('/trials/e1/comparison', { ...DEFAULT_CONFIG, queryStaleTimeMs: 20 });
    const exportButton = await screen.findByRole('button', { name: 'Export report' });
    fireEvent.click(exportButton);
    expect(await screen.findByText('Generating report…')).toBeInTheDocument();
    expect(exportButton).toBeDisabled();
    await vi.waitFor(() => {
      expect(reads).toBeGreaterThanOrEqual(1);
    });
    completed = true;
    await vi.waitFor(() => {
      expect(view.state.location.pathname).toBe('/reports/r1');
    });
    expect(await screen.findByTitle('Report preview')).toHaveAttribute(
      'sandbox',
      'allow-same-origin',
    );
    expect(authored).toHaveBeenCalledWith('Bearer test-report-token', {
      kind: 'experiment',
      id: 'e1',
    });
    expect(reads).toBeGreaterThanOrEqual(2);
  } finally {
    setToken(null);
  }
});

it('unblocks report export when a restart interrupted the previous job', async () => {
  const job = { id: 'interrupted', kind: 'experiment', target_id: 'e1' };
  server.use(
    http.post(apiUrl('/reports'), () =>
      HttpResponse.json({ ...job, status: 'RUNNING' }, { status: 202 }),
    ),
    http.get(apiUrl('/reports/interrupted'), () => HttpResponse.json({ ...job, status: 'ERROR' })),
  );
  mount('/trials/e1/comparison');
  const exportButton = await screen.findByRole('button', { name: 'Export report' });
  fireEvent.click(exportButton);
  expect(await screen.findByRole('alert')).toHaveTextContent('Report generation failed.');
  expect(exportButton).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Download HTML report' })).toBeNull();
});
