import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { appRoutes } from './router';
import { AppProviders } from './providers';
describe('App', () => {
  it('renders the notebook main landmark', async () => {
    const router = createMemoryRouter(appRoutes());
    render(
      <AppProviders live={false}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    expect(await screen.findByRole('heading', { level: 1, name: 'Bench' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
