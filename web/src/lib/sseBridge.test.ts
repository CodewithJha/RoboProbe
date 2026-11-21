import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { EVENT_TYPES } from './sse';
import { applyServerEvent, EVENT_QUERIES } from './sseBridge';
describe('SSE query bridge', () => {
  it.each(EVENT_TYPES)('handles documented event %s', (type) => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    applyServerEvent(client, { type, id: '1', data: { campaign_id: 'c1', run_id: 'r1' } });
    expect(EVENT_QUERIES[type]).toBeDefined();
    if (type === 'alert')
      expect(client.getQueryData(['alerts'])).toEqual([{ campaign_id: 'c1', run_id: 'r1' }]);
    else expect(invalidate).toHaveBeenCalled();
    client.clear();
  });
  it('patches campaign data without creating incomplete records', () => {
    const client = new QueryClient();
    client.setQueryData(['campaigns', 'c1'], { id: 'c1', status: 'RUNNING', name: 'probe' });
    applyServerEvent(client, {
      type: 'campaign.updated',
      id: '3',
      data: { campaign_id: 'c1', status: 'PAUSED' },
    });
    expect(client.getQueryData(['campaigns', 'c1'])).toMatchObject({
      name: 'probe',
      status: 'PAUSED',
    });
    applyServerEvent(client, {
      type: 'campaign.updated',
      id: '4',
      data: { campaign_id: 'missing', status: 'PAUSED' },
    });
    expect(client.getQueryData(['campaigns', 'missing'])).toBeUndefined();
  });
  it('deduplicates complete run records while preserving infinite page cursors', () => {
    const client = new QueryClient();
    const run = { id: 'r1', campaign_id: 'c1', ordinal: 1, scenario: {} };
    client.setQueryData(['campaigns', 'c1', 'runs', {}], {
      pages: [
        { items: [run], next_cursor: 'next' },
        { items: [run], next_cursor: null },
      ],
      pageParams: [undefined, 'next'],
    });
    applyServerEvent(client, { type: 'run.finished', id: '5', data: { campaign_id: 'c1', run } });
    expect(client.getQueryData(['campaigns', 'c1', 'runs', {}])).toMatchObject({
      pages: [
        { items: [run], next_cursor: 'next' },
        { items: [], next_cursor: null },
      ],
    });
  });
});
