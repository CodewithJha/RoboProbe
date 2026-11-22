import { readFileSync } from 'node:fs';
import { URL as NodeURL } from 'node:url';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { parse } from 'yaml';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { Component } from './WizardPage';

const defaultCliConfig = readFileSync(
  new NodeURL('../../../../backend/tests/fixtures/campaigns/wizard-default.yaml', import.meta.url),
  'utf8',
);

const version = '09cf763f2e0d';
const configSeed = 20261119;
let payload: unknown;
let requestKey: string | null;
let requestCount = 0;
const server = setupServer(
  http.get(apiUrl('/spaces'), () =>
    HttpResponse.json({ items: [{ id: 'warehouse_v1', version, name: 'Warehouse' }] }),
  ),
  http.get(apiUrl(`/spaces/warehouse_v1/versions/${version}`), () =>
    HttpResponse.json({
      definition: {
        parameters: [
          { id: 'robot.speed', name: 'Speed', type: 'float', nominal: 2, low: 1, high: 3 },
        ],
      },
    }),
  ),
  http.get(apiUrl('/sut-profiles'), () =>
    HttpResponse.json({ items: [{ id: 'k2d_default', backend: 'kinematic2d' }] }),
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
      strategies: [{ id: 'S-RANDOM', description: 'Random', params_schema: { type: 'object' } }],
    }),
  ),
  http.post(apiUrl('/campaigns'), async ({ request }) => {
    requestCount += 1;
    payload = await request.json();
    requestKey = request.headers.get('idempotency-key');
    return HttpResponse.json({ id: 'created' }, { status: 201 });
  }),
);

beforeAll(() => {
  server.listen();
});
beforeEach(() => {
  requestCount = 0;
  payload = undefined;
  requestKey = null;
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => {
  server.close();
});

function renderWizard() {
  const router = createMemoryRouter([
    { path: '/', Component },
    { path: '/campaigns/created/console', Component: () => <h1>Created campaign</h1> },
  ]);
  return render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

async function openReview() {
  await screen.findByRole('checkbox', { name: 'Pin Speed' });
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('option', { name: 'kinematic2d · 1 online' });
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  return screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Campaign YAML' });
}

it('pins a parameter, previews the same campaign sent to the API, and opens the console', async () => {
  renderWizard();
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
    space: { id: 'warehouse_v1', version },
    pins: { 'robot.speed': 2 },
  });
  expect(expected).toEqual({ schema_version: 1, ...Object.assign({}, payload) });
  expect(await screen.findByRole('heading', { name: 'Created campaign' })).toBeInTheDocument();
});

it('submits the default YAML unchanged and handles two submissions as one request', async () => {
  vi.spyOn(crypto, 'getRandomValues').mockImplementation((array) => {
    if (array instanceof Uint32Array) array.set([configSeed]);
    return array;
  });
  renderWizard();
  const preview = await openReview();
  expect(preview.value).toBe(defaultCliConfig);
  const form = preview.closest('form');
  if (!form) throw new Error('Campaign wizard form is missing');
  act(() => {
    fireEvent.submit(form);
    fireEvent.submit(form);
  });
  expect(await screen.findByRole('heading', { name: 'Created campaign' })).toBeInTheDocument();
  expect(requestCount).toBe(1);
  expect(requestKey).toBeTruthy();
  expect(payload).toMatchObject({
    backend: 'kinematic2d',
    strategy: { id: 'S-RANDOM', seed: configSeed },
    sut_profile_id: 'k2d_default',
    pins: {},
    start: true,
  });
});

it('returns from review and associates a server validation message with the rejected field', async () => {
  server.use(
    http.post(apiUrl('/campaigns'), () =>
      HttpResponse.json(
        {
          errors: [{ pointer: '/body/budget', detail: 'Budget exceeds current worker capacity.' }],
        },
        { status: 422 },
      ),
    ),
  );
  renderWizard();
  await openReview();
  fireEvent.click(screen.getByRole('button', { name: 'Create campaign' }));
  const budget = await screen.findByRole('spinbutton', { name: 'Budget' });
  expect(budget).toHaveAttribute('aria-invalid', 'true');
  expect(budget).toHaveAccessibleDescription('Budget exceeds current worker capacity.');
  expect(screen.getByRole('spinbutton', { name: 'Batch size' })).not.toHaveAttribute(
    'aria-invalid',
  );
});
