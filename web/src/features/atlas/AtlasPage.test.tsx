import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { apiUrl, type Schema } from '../../api/client';
import { AppProviders } from '../../app/providers';
import { Component as ConsolePage } from '../console/ConsolePage';
import { atlasConfig } from './atlasConfig';
import { Component } from './AtlasPage';

const campaign: Schema['CampaignOut'] = {
  id: 'c1',
  status: 'RUNNING',
  name: 'Warehouse sweep',
  strategy: { id: 'S-RANDOM', seed: 42 },
  backend: 'kinematic2d',
  budget: 20,
  batch_size: 1,
  repeats: 1,
  modes_found: 1,
  space: { id: 's1', version: 'v1' },
  pins: {},
};
const medoidRun: Schema['RunOut'] = {
  id: 'r1',
  campaign_id: 'c1',
  ordinal: 1,
  repeat_index: 0,
  seed: 42,
  phase: 'falsify',
  status: 'DONE',
  verdict: 'PASS',
  scenario: { values: { speed: 1, light: 5, distance: 5 } },
};
const queue = vi.fn();
const requestSlice = vi.fn();
const server = setupServer(
  http.get(apiUrl('/campaigns/c1'), () => HttpResponse.json(campaign)),
  http.get(apiUrl('/spaces/s1/versions/v1'), () =>
    HttpResponse.json({
      definition: {
        parameters: [
          { id: 'distance', type: 'int', low: 1, high: 10, nominal: 2 },
          { id: 'speed' },
          { id: 'light' },
        ],
      },
    }),
  ),
  http.get(apiUrl('/meta'), () => HttpResponse.json({ defaults: { risk_slice_resolution: 10 } })),
  http.get(apiUrl('/campaigns/c1/modes'), () =>
    HttpResponse.json({
      items: [{ id: 'm1', code: 'FM-01', label: 'Collision', medoid_run_id: 'r1' }],
    }),
  ),
  http.get(apiUrl('/campaigns/c1/risk'), () =>
    HttpResponse.json({
      volumes: { safe: 0.2, uncertain: 0.3, failure: 0.5, safe_ci: [0.15, 0.25] },
      robustness_score: 0.4,
    }),
  ),
  http.get(apiUrl('/runs/r1'), () => HttpResponse.json(medoidRun)),
  http.get(apiUrl('/campaigns/c1/risk/slice'), ({ request }) => {
    const params = new URL(request.url).searchParams;
    const x = params.get('x');
    const y = params.get('y');
    const anchor = params.get('anchor');
    requestSlice(x, y, anchor, params.get('anchor_values'));
    return HttpResponse.json({
      x_param: x,
      y_param: y,
      anchor,
      resolution: 10,
      log_x: false,
      log_y: false,
      x_values: [1, 2],
      y_values: [5, 6],
      p_fail: [
        [0.1, 0.3],
        [0.5, 0.7],
      ],
      region: [
        [0, 1],
        [1, 2],
      ],
    });
  }),
  http.post(apiUrl('/campaigns/c1/runs'), async ({ request }) => {
    queue(await request.json());
    return HttpResponse.json({ run_ids: ['r2'] });
  }),
);
beforeAll(() => {
  server.listen();
});
afterEach(() => {
  vi.useRealTimers();
  server.resetHandlers();
  queue.mockClear();
  requestSlice.mockClear();
  vi.unstubAllGlobals();
});
afterAll(() => {
  server.close();
});

it('debounces rapid anchor edits, shares the latest values, and queues the physical point', async () => {
  const router = createMemoryRouter([{ path: '/campaigns/:id/atlas', Component }], {
    initialEntries: ['/campaigns/c1/atlas?x=speed&y=light&anchor=mode%3AFM-01'],
  });
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  const selected = await screen.findByRole('region', { name: 'Selected risk slice' });
  expect(within(selected).getByRole('heading', { name: 'speed × light' })).toBeInTheDocument();
  expect(within(selected).getByRole('combobox', { name: 'Anchor' })).toHaveValue('mode:FM-01');
  const slider = await screen.findByRole('slider', { name: 'distance' });
  expect(slider).toHaveValue('5');
  await screen.findByText('Risk data table');
  requestSlice.mockClear();
  slider.focus();
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  fireEvent.change(slider, { target: { value: '6' } });
  await act(() => vi.advanceTimersByTimeAsync(atlasConfig.anchorDebounceMs / 2));
  fireEvent.change(slider, { target: { value: '7' } });
  expect(slider).toHaveValue('7');
  await act(() => vi.advanceTimersByTimeAsync(atlasConfig.anchorDebounceMs - 1));
  expect(requestSlice).not.toHaveBeenCalled();
  expect(new URLSearchParams(router.state.location.search).has('anchor_values')).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  vi.useRealTimers();
  await waitFor(() => {
    expect(requestSlice).toHaveBeenCalledExactlyOnceWith(
      'speed',
      'light',
      'mode:FM-01',
      '{"distance":7}',
    );
  });
  expect(new URLSearchParams(router.state.location.search).get('anchor_values')).toBe(
    '{"distance":7}',
  );
  expect(slider).toHaveFocus();
  fireEvent.click(await screen.findByText('Risk data table'));
  fireEvent.click(await screen.findByRole('button', { name: /Probe speed 2, light 6/ }));
  const submit = await screen.findByRole('button', { name: 'Queue manual run' });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  expect(await screen.findByText(/Manual run queued/)).toBeInTheDocument();
  expect(queue).toHaveBeenCalledWith({ values: { speed: 2, light: 6, distance: 7 }, repeats: 1 });
  fireEvent.change(within(selected).getByRole('combobox', { name: 'Anchor' }), {
    target: { value: 'nominal' },
  });
  await screen.findByText('Risk data table');
  expect(requestSlice).toHaveBeenCalledWith('speed', 'light', 'nominal', null);
});

it('discards a pending anchor edit on navigation, including after returning to the same URL', async () => {
  const nominal = '/campaigns/c1/atlas?x=speed&y=light&anchor=nominal';
  const medoid = '/campaigns/c1/atlas?x=speed&y=light&anchor=mode%3AFM-01';
  const router = createMemoryRouter([{ path: '/campaigns/:id/atlas', Component }], {
    initialEntries: [nominal, medoid],
  });
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );

  const slider = await screen.findByRole('slider', { name: 'distance' });
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  fireEvent.change(slider, { target: { value: '8' } });
  expect(slider).toHaveValue('8');
  await act(async () => router.navigate(-1));
  expect(slider).toHaveValue('2');
  await act(async () => router.navigate(1));
  expect(slider).toHaveValue('5');
  await act(async () => vi.advanceTimersByTimeAsync(atlasConfig.anchorDebounceMs));
  expect(new URLSearchParams(router.state.location.search).has('anchor_values')).toBe(false);
  expect(requestSlice).not.toHaveBeenCalledWith('speed', 'light', 'mode:FM-01', '{"distance":8}');
});

it('restores custom anchor values and shows the queued probe in Console after its live event', async () => {
  const source = Object.assign(new EventTarget(), { close: vi.fn() });
  vi.stubGlobal('EventSource', function TestEventSource() {
    return source;
  });
  const probeRun: Schema['RunOut'] = {
    ...medoidRun,
    id: 'r2',
    ordinal: 2,
    phase: 'manual',
    scenario: { values: { speed: 2, light: 6, distance: 7 } },
  };
  let runs = [medoidRun];
  server.use(
    http.get(apiUrl('/campaigns/c1/progress'), () =>
      HttpResponse.json({ campaign_id: 'c1', counts: { done: runs.length } }),
    ),
    http.get(apiUrl('/campaigns/c1/runs'), () => HttpResponse.json({ items: runs })),
  );
  const search = new URLSearchParams({
    x: 'speed',
    y: 'light',
    anchor: 'mode:FM-01',
    anchor_values: JSON.stringify({ distance: 7 }),
  });
  const router = createMemoryRouter(
    [
      { path: '/campaigns/:id/atlas', Component },
      { path: '/campaigns/:id/console', Component: ConsolePage },
    ],
    { initialEntries: [`/campaigns/c1/atlas?${search}`] },
  );
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );

  expect(await screen.findByRole('slider', { name: 'distance' })).toHaveValue('7');
  fireEvent.click(await screen.findByText('Risk data table'));
  expect(requestSlice).toHaveBeenCalledWith('speed', 'light', 'mode:FM-01', '{"distance":7}');
  fireEvent.click(await screen.findByRole('button', { name: /Probe speed 2, light 6/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Queue manual run' }));
  const consoleLink = await screen.findByRole('link', { name: 'Open campaign console' });
  expect(queue).toHaveBeenCalledWith({ values: { speed: 2, light: 6, distance: 7 }, repeats: 1 });
  fireEvent.click(consoleLink);

  expect(await screen.findByRole('link', { name: 'Run #1' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Run #2' })).not.toBeInTheDocument();
  runs = [probeRun, medoidRun];
  act(() => {
    source.dispatchEvent(
      new MessageEvent('run.finished', {
        data: JSON.stringify({ campaign_id: 'c1', run_id: 'r2' }),
        lastEventId: '1',
      }),
    );
  });
  expect(await screen.findByRole('link', { name: 'Run #2' })).toHaveAttribute('href', '/runs/r2');
  expect(await screen.findByText('2 / 20 runs')).toBeInTheDocument();
});
