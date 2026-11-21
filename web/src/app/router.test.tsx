import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { AppProviders } from './providers';
import { appRoutes } from './router';
import { DEFAULT_CONFIG, setConfig } from '../lib/config';
import { ProblemError } from '../api/client';
import { RouteError } from './ProblemView';
afterEach(() => {
  localStorage.clear();
  setConfig(DEFAULT_CONFIG);
  document.documentElement.removeAttribute('data-theme');
});
function mount(path: string) {
  const router = createMemoryRouter(appRoutes(), { initialEntries: [path] });
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}
const ROUTES = [
  ['/', 'Bench'],
  ['/campaigns', 'Campaigns'],
  ['/campaigns/new', 'New campaign'],
  ['/campaigns/c1', 'Campaign console'],
  ['/campaigns/c1/runs', 'Run entries'],
  ['/campaigns/c1/casebook', 'Casebook'],
  ['/campaigns/c1/atlas', 'Risk atlas'],
  ['/campaigns/c1/insights', 'Insights'],
  ['/campaigns/c1/settings', 'Settings'],
  ['/runs/r1', 'Run entry'],
  ['/trials', 'Trials'],
  ['/trials/e1', 'Experiment'],
  ['/spaces', 'Spaces'],
  ['/spaces/warehouse/v1', 'Scenario space'],
  ['/workbench', 'Workbench'],
  ['/settings', 'Settings'],
  ['/reports', 'Reports'],
  ['/reports/job1', 'Report'],
] as const;
describe('notebook routes', () => {
  it.each(ROUTES)('renders %s', async (path, heading) => {
    mount(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });
  it('renders unknown routes and provides a way back', async () => {
    mount('/missing');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Return to Bench' })).toHaveAttribute('href', '/');
  });
  it('hides feature-flagged navigation and routes', async () => {
    setConfig({ ...DEFAULT_CONFIG, featureFlags: { trials: false, reports: false } });
    mount('/trials');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Trials' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Reports' })).not.toBeInTheDocument();
  });
  it('keeps navigation accessible and persists theme choice', async () => {
    mount('/');
    await screen.findByRole('heading', { name: 'Bench' });
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Bench' })).toHaveAttribute('aria-current', 'page');
    fireEvent.click(screen.getByRole('button', { name: 'System theme. Change theme' }));
    await waitFor(() => {
      expect(localStorage.getItem('roboprobe.theme')).toBe('light');
    });
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  });
  it('renders structured route errors', async () => {
    const router = createMemoryRouter([
      {
        path: '/',
        loader: () => {
          throw new ProblemError(500, {
            title: 'Analysis unavailable',
            detail: 'Try again later',
            trace_id: 'trace-one',
          });
        },
        ErrorBoundary: RouteError,
      },
    ]);
    render(<RouterProvider router={router} />);
    expect(
      await screen.findByRole('heading', { name: 'Analysis unavailable' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Try again later')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy trace ID trace-one' })).toBeInTheDocument();
  });
});
