import { fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterAll, beforeAll, expect, it, vi } from 'vitest';
import { apiUrl } from '../../api/client';
import { AppProviders } from '../../app/providers';
import { Component } from './AtlasPage';

const queue = vi.fn();
const requestSlice = vi.fn();
const server = setupServer(
  http.get(apiUrl('/campaigns/c1'), () =>
    HttpResponse.json({ space: { id: 's1', version: 'v1' }, pins: {} }),
  ),
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
  http.get(apiUrl('/runs/r1'), () =>
    HttpResponse.json({ scenario: { values: { speed: 1, distance: 5, light: 200 } } }),
  ),
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
afterAll(() => {
  server.close();
});

it('restores a shared pair and medoid, then queues the physical point with the anchor values', async () => {
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
  fireEvent.change(slider, { target: { value: '7' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply values' }));
  fireEvent.click(await screen.findByText('Risk data table'));
  expect(requestSlice).toHaveBeenCalledWith('speed', 'light', 'mode:FM-01', '{"distance":7}');
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
