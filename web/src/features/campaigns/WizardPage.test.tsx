import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { parse } from 'yaml';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { Component } from './WizardPage';

const version = '0123456789ab';
let payload: unknown;
let requestKey: string | null;
const server = setupServer(
  http.get(apiUrl('/spaces'), () =>
    HttpResponse.json({ items: [{ id: 'warehouse', version, name: 'Warehouse' }] }),
  ),
  http.get(apiUrl(`/spaces/warehouse/versions/${version}`), () =>
    HttpResponse.json({
      definition: {
        parameters: [
          { id: 'robot.speed', name: 'Speed', type: 'float', nominal: 2, low: 1, high: 3 },
        ],
      },
    }),
  ),
  http.get(apiUrl('/sut-profiles'), () =>
    HttpResponse.json({ items: [{ id: 'demo_robot', backend: 'kinematic2d' }] }),
  ),
  http.get(apiUrl('/workers'), () =>
    HttpResponse.json({ items: [{ id: 'one', status: 'IDLE', backend: 'kinematic2d' }] }),
  ),
  http.get(apiUrl('/meta'), () =>
    HttpResponse.json({
      backends: [
        { id: 'kinematic2d', capabilities: { typical_episode_wall_s: 2 } },
        { id: 'gazebo' },
      ],
      strategies: [{ id: 'S-PROBE', description: 'Probe', params_schema: { type: 'object' } }],
    }),
  ),
  http.post(apiUrl('/campaigns'), async ({ request }) => {
    payload = await request.json();
    requestKey = request.headers.get('idempotency-key');
    return HttpResponse.json({ id: 'created' }, { status: 201 });
  }),
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

it('pins a parameter, previews the same campaign sent to the API, and opens the console', async () => {
  const router = createMemoryRouter([
    { path: '/', Component },
    { path: '/campaigns/created/console', Component: () => <h1>Created campaign</h1> },
  ]);
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Pin Speed' }));
  expect(screen.getByText('0 free parameters')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(screen.getByRole('option', { name: 'gazebo · no online workers' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(screen.getByRole('spinbutton', { name: 'Batch size' })).toHaveValue(1);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  const preview = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Campaign YAML' });
  const expected: unknown = parse(preview.value);
  fireEvent.click(screen.getByRole('button', { name: 'Create campaign' }));
  await waitFor(() => {
    expect(requestKey).toBeTruthy();
  });
  expect(payload).toMatchObject({
    space: { id: 'warehouse', version },
    pins: { 'robot.speed': 2 },
  });
  expect(expected).toEqual({ schema_version: 1, ...Object.assign({}, payload) });
  expect(await screen.findByRole('heading', { name: 'Created campaign' })).toBeInTheDocument();
});
