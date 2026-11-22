import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { AppProviders } from '../../app/providers';
import { apiUrl } from '../../api/client';
import { Component } from './SpacesPage';

const server = setupServer(
  http.get(apiUrl('/spaces'), () =>
    HttpResponse.json({
      items: [
        { id: 'warehouse_v1', version: '2b4d5a96d21a', name: 'Warehouse', schema_version: 1 },
      ],
    }),
  ),
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

it('lists registered spaces', async () => {
  const router = createMemoryRouter([{ path: '/', Component }]);
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  expect(await screen.findByRole('link', { name: 'Warehouse' })).toHaveAttribute(
    'href',
    '/spaces/warehouse_v1/2b4d5a96d21a',
  );
});
