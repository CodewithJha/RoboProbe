import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { AppProviders } from './providers';
import { GlobalShortcuts } from './shortcuts';
import { getLastCampaign } from '../lib/lastCampaign';

afterEach(() => {
  vi.restoreAllMocks();
});

function chord(target: HTMLElement, first: string, second: string) {
  fireEvent.keyDown(target, { key: first, bubbles: true });
  fireEvent.keyDown(target, { key: second, bubbles: true });
}

function mount(initial: string) {
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <>
            <input aria-label="Search campaigns" />
            <GlobalShortcuts />
          </>
        ),
      },
      { path: '/campaigns/:id/console', element: <h1>Campaign console</h1> },
    ],
    { initialEntries: [initial] },
  );
  render(
    <AppProviders live={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

it('opens the shortcuts dialog on ?', async () => {
  mount('/');
  fireEvent.keyDown(document.body, { key: '?', shiftKey: true });
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
});

it('navigates to bench on g b and to the last campaign on g c', async () => {
  sessionStorage.setItem('roboprobe.last-campaign', 'camp-1');
  const router = mount('/');
  chord(document.body, 'g', 'b');
  expect(router.state.location.pathname).toBe('/');
  chord(document.body, 'g', 'c');
  await waitFor(() => {
    expect(router.state.location.pathname).toBe('/campaigns/camp-1/console');
  });
  expect(getLastCampaign()).toBe('camp-1');
});