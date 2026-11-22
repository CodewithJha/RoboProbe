import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { DEFAULT_CONFIG } from '../../lib/config';
import { setToken } from '../../lib/token';
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
const reportHtml =
  '<!doctype html><html lang="en"><head></head><body><h1>Report body</h1></body></html>';

beforeAll(() => {
  server.listen();
});
afterEach(() => {
  server.resetHandlers();
  setToken(null);
});
afterAll(() => {
  server.close();
});

function renderReport() {
  const router = createMemoryRouter([{ path: '/reports/:id', Component }], {
    initialEntries: ['/reports/job-1'],
  });
  return render(
    <AppProviders config={DEFAULT_CONFIG} live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

it('loads the report with the session bearer and embeds its HTML without scripts', async () => {
  let authorization: string | null | undefined;
  setToken('report-session-token');
  server.use(
    http.get(apiUrl('/reports/job-1/content'), ({ request }) => {
      authorization = request.headers.get('authorization');
      return HttpResponse.html(reportHtml);
    }),
  );
  renderReport();
  const frame = await screen.findByTitle('Report preview');
  expect(authorization).toBe('Bearer report-session-token');
  expect(frame.getAttribute('srcdoc')).toContain('<h1>Report body</h1>');
  expect(frame.getAttribute('sandbox')).toContain('allow-modals');
  expect(frame.getAttribute('sandbox') ?? '').not.toMatch(/allow-scripts/);
  expect(screen.getByRole('button', { name: 'Download HTML' })).toBeEnabled();
});

it('offers the archive without trying to preview binary report content', async () => {
  server.use(
    http.get(apiUrl('/reports/job-1'), () =>
      HttpResponse.json({
        id: 'job-1',
        kind: 'bundle',
        target_id: 'c1',
        status: 'COMPLETED',
      }),
    ),
    http.get(apiUrl('/reports/job-1/content'), () =>
      HttpResponse.arrayBuffer(new Uint8Array([1, 2, 3]).buffer, {
        headers: { 'Content-Type': 'application/zstd' },
      }),
    ),
  );
  renderReport();
  expect(await screen.findByRole('button', { name: 'Download archive' })).toBeEnabled();
  expect(screen.queryByTitle('Report preview')).not.toBeInTheDocument();
});
