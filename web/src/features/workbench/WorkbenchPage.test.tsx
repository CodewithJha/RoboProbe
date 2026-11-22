import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { Component } from './WorkbenchPage';

const server = setupServer(
  http.get(apiUrl('/workers'), () =>
    HttpResponse.json({
      items: [
        {
          id: 'w1',
          backend: 'kinematic2d',
          status: 'IDLE',
          version: 'dev',
          last_heartbeat: new Date(Date.now() - 120_000).toISOString(),
        },
      ],
    }),
  ),
  http.get(apiUrl('/meta'), () => HttpResponse.json({ limits: { heartbeat_timeout_s: 30 } })),
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

it('highlights stale heartbeats using the meta timeout', async () => {
  render(
    <AppProviders live={false}>
      <Component />
    </AppProviders>,
  );
  expect(await screen.findByTitle('Heartbeat is stale')).toBeInTheDocument();
});
