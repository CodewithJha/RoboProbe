import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import type { Schema } from '../../api/client';
import { Component } from './RunPage';

const id = '68202128-84c1-4704-8157-321b5efb1429';
const campaignId = 'd11f2c46-46fa-4244-92b0-8f2eafa035af';
const run: Schema['RunOut'] = {
  id,
  campaign_id: campaignId,
  ordinal: 7,
  repeat_index: 0,
  status: 'DONE',
  phase: 'explore',
  seed: 7,
  verdict: 'FAIL',
  robustness: -0.15,
  primary_failure: 'F-COL',
  scenario: { hash: 'abc123456789', values: { speed: 0.4 } },
  oracles: [
    {
      oracle_id: 'O-CLEAR',
      first_violation_t: 1,
      robustness: -0.15,
      violated: true,
      details: { contact: true },
    },
  ],
  manifest: { config_snapshot: { oracles: { clear: { d_safe: 0.15 }, loc: { e_max: 0.2 } } } },
};
const trace: Schema['TraceOut'] = {
  t: [0, 1, 2],
  hz: 1,
  source_hz: 1,
  truncated: false,
  columns: {
    gt_x: [0, 1, 2],
    gt_y: [1, 2, 3],
    gt_yaw: [0, 0, 0],
    est_x: [0, 1, 2],
    est_y: [1, 2, 3],
    nav_status: [1, 1, 2],
    min_obstacle_dist: [0.4, 0.1, 0.2],
    cmd_v: [0.3, 0.4, 0.3],
    meas_v: [0.2, 0.4, 0.5],
  },
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function Console() {
  return <p>{useLocation().search}</p>;
}
function open(details: Schema['RunOut'] = run) {
  const fetcher = vi.fn((request: Request) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith(':replay'))
      return Response.json({ run_ids: ['new-run'] }, { status: 202 });
    if (url.pathname.endsWith('/trace')) return Response.json(trace);
    if (url.pathname.endsWith('/artifacts')) return Response.json([]);
    if (url.pathname.endsWith('/meta')) return Response.json({ limits: { max_manual_repeats: 5 } });
    if (url.pathname.endsWith(id)) return Response.json(details);
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/runs/${id}`]}>
        <Routes>
          <Route path="/runs/:id" element={<Component />} />
          <Route path="/campaigns/:id" element={<Console />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetcher;
}

test.skip('links the timeline scrubber to all timeline cursors and the trajectory', async () => {
  open();
  const slider = await screen.findByRole('slider', { name: 'Clearance inspection time' });
  expect(screen.getByText('Safe clearance: 0.15 m')).toBeInTheDocument();
  fireEvent.change(slider, { target: { value: '1' } });
  await waitFor(() => {
    expect(screen.getAllByTestId('timeline-cursor')).toHaveLength(4);
    for (const cursor of screen.getAllByTestId('timeline-cursor'))
      expect(cursor).toHaveAttribute('data-time', '1');
    expect(screen.getByTestId('trajectory-cursor')).toHaveAttribute('data-time', '1');
  });
  const trajectory = screen.getByRole('application', { name: /Interactive trajectory/u });
  fireEvent.keyDown(trajectory, { key: '+' });
  expect(screen.getByTestId('trajectory-viewport').getAttribute('transform')).toContain(
    'scale(1.2)',
  );
  fireEvent.keyDown(trajectory, { key: '0' });
  expect(screen.getByTestId('trajectory-viewport').getAttribute('transform')).toContain('scale(1)');
});

test.skip('queues replay with the selected seed option and highlights the returned run', async () => {
  const fetcher = open();
  fireEvent.click(await screen.findByRole('button', { name: 'Replay' }));
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Repeats' }), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Use fresh seeds' }));
  fireEvent.click(screen.getByRole('button', { name: 'Queue replay' }));
  expect(await screen.findByText('?highlight=new-run')).toBeInTheDocument();
  const request = fetcher.mock.calls.find(([call]) => call.url.endsWith(':replay'))?.[0];
  expect(request?.method).toBe('POST');
  expect(await request?.json()).toEqual({ repeats: 2, fresh_seeds: true });
});

test('shows the recorded infrastructure error and omits oracle scores for invalid runs', async () => {
  open({
    ...run,
    verdict: 'INVALID',
    manifest: { ...(run.manifest ?? {}), infra_error: 'Simulator disconnected' },
  });
  expect(await screen.findByText('Simulator disconnected')).toBeInTheDocument();
  expect(screen.queryByRole('meter')).not.toBeInTheDocument();
});

test('renders passing verdict with oracle robustness', async () => {
  open({ ...run, verdict: 'PASS', primary_failure: null, robustness: 0.5 });
  expect(await screen.findByRole('meter', { name: 'Robustness' })).toHaveAttribute(
    'aria-valuenow',
    '0.5',
  );
});
