import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import type { Schema } from '../../../api/client';
import { CasebookGrid } from './CasebookGrid';

const items = [
  {
    id: 'mode-a',
    campaign_id: 'campaign-a',
    code: 'FM-01',
    label: 'Collision',
    primary_class: 'F-COL',
    size: 12,
    version: 3,
    status: 'open',
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
    provisional: false,
  },
] as unknown as Schema['FailureModeOut'][];
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

test('shows evidence, filters cases, and queues confirmation for the selected mode', async () => {
  const evidence = {
    ...items[0],
    medoid_run_id: 'medoid-a',
    minimal_run_id: 'minimal-a',
    characteristic: ['speed'],
    param_ranges: { speed: { unit: 'm/s', q05: 0.2, q95: 0.5, space_coverage: 0.4 } },
    rules: [
      {
        conditions: [{ param: 'speed', op: '≥', threshold_physical: 0.2 }],
        precision: 0.8,
        support: 9,
      },
    ],
    reproducibility: 0.75,
  };
  const fetcher = vi.fn((request: Request) =>
    request.method === 'POST'
      ? Response.json({ run_ids: ['queued'] }, { status: 202 })
      : Response.json({ items: [evidence, ...items.slice(1)] }),
  );
  setup(fetcher);
  const card = (await screen.findAllByRole('article'))[0];
  if (!card) throw new Error('Case card is missing');
  expect(within(card).getByRole('link', { name: 'Medoid run' })).toHaveAttribute(
    'href',
    '/runs/medoid-a',
  );
  expect(within(card).getByText(/Precision 0.8/)).toBeVisible();
  expect(within(card).getByText('Reproducibility 0.75')).toBeVisible();
  fireEvent.change(screen.getByRole('combobox', { name: 'Failure class' }), {
    target: { value: 'F-COL' },
  });
  expect(screen.getAllByRole('article')).toHaveLength(1);
  fireEvent.click(within(card).getByRole('button', { name: 'Confirm interaction' }));
  expect(await within(card).findByText('Confirmation pending')).toBeVisible();
  expect(
    fetcher.mock.calls.some(([request]) =>
      new URL(request.url).pathname.endsWith('/mode-a:confirm-interaction'),
    ),
  ).toBe(true);
});
