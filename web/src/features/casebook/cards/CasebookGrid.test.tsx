import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import type { Schema } from '../../../api/client';
import { CasebookGrid } from './CasebookGrid';

const items: Schema['FailureModeOut'][] = [
  {
    id: 'mode-a',
    campaign_id: 'campaign-a',
    code: 'FM-01',
    label: 'Collision',
    primary_class: 'F-COL',
    size: 12,
    version: 3,
    status: 'open',
    label_is_user: false,
    provisional: true,
  },
  {
    id: 'mode-b',
    campaign_id: 'campaign-a',
    code: 'FM-02',
    label: 'Stuck',
    primary_class: 'F-STUCK',
    size: 8,
    version: 1,
    status: 'open',
    label_is_user: false,
    provisional: false,
  },
  {
    id: 'mode-c',
    campaign_id: 'campaign-a',
    code: 'FM-03',
    label: 'Timeout',
    primary_class: 'F-TIMEOUT',
    size: 6,
    version: 1,
    status: 'open',
    label_is_user: false,
    provisional: false,
  },
];
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup(fetcher: (request: Request) => Response | Promise<Response>) {
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CasebookGrid campaignId="campaign-a" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test('shows three cases and rolls back an optimistic rename after an ETag conflict', async () => {
  let resolveReply: (response: Response) => void = () => {
    throw new Error('Missing response');
  };
  const reply = new Promise<Response>((resolve) => {
    resolveReply = resolve;
  });
  const fetcher = vi.fn((request: Request) =>
    request.method === 'PATCH' ? reply : Response.json({ items }),
  );
  setup(fetcher);
  const card = (await screen.findAllByRole('article'))[0];
  expect(screen.getAllByRole('article')).toHaveLength(3);
  expect(screen.getByText('Provisional')).toBeVisible();
  if (!card) throw new Error('Case card is missing');
  fireEvent.click(within(card).getByRole('button', { name: 'Rename' }));
  fireEvent.change(within(card).getByRole('textbox', { name: 'Case name' }), {
    target: { value: 'Edited case' },
  });
  fireEvent.click(within(card).getByRole('button', { name: 'Save name' }));
  expect(await within(card).findByRole('heading', { name: 'Edited case' })).toBeVisible();
  await waitFor(() => {
    expect(
      fetcher.mock.calls
        .find(([request]) => request.method === 'PATCH')?.[0]
        .headers.get('If-Match'),
    ).toBe('W/"3"');
  });
  resolveReply(Response.json({ detail: 'Version changed' }, { status: 412 }));
  expect(await within(card).findByRole('heading', { name: 'Collision' })).toBeVisible();
  expect(within(card).getByRole('alert')).toHaveTextContent('Changed elsewhere');
});

test('sends the row version with a status change', async () => {
  const fetcher = vi.fn((request: Request) =>
    request.method === 'PATCH'
      ? Response.json({ ...items[0], status: 'accepted', version: 4 })
      : Response.json({ items }),
  );
  setup(fetcher);
  const card = (await screen.findAllByRole('article'))[0];
  if (!card) throw new Error('Case card is missing');
  fireEvent.change(within(card).getByRole('combobox', { name: 'Status' }), {
    target: { value: 'accepted' },
  });
  await waitFor(() => {
    expect(
      fetcher.mock.calls
        .find(([request]) => request.method === 'PATCH')?.[0]
        .headers.get('If-Match'),
    ).toBe('W/"3"');
  });
});
