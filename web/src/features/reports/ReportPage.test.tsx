import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { DEFAULT_CONFIG } from '../../lib/config';
import { Component } from './ReportPage';

const server = setupServer(
  http.get(apiUrl('/reports/job-1'), () =>
    HttpResponse.json({
      id: 'job-1',
      kind: 'campaign',
      target_id: 'c1',
      status: 'COMPLETED',
    }),
  ),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it('embeds the report without allow-scripts', async () => {
  const router = createMemoryRouter([{ path: '/reports/:id', Component }], {
    initialEntries: ['/reports/job-1'],
  });
  render(
    <AppProviders config={DEFAULT_CONFIG} live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  const frame = await screen.findByTitle('Report preview');
  expect(frame).toHaveAttribute('sandbox', 'allow-same-origin');
  expect(frame.getAttribute('sandbox') ?? '').not.toMatch(/allow-scripts/);
});