/** Server events patch only complete records; otherwise invalidate authoritative queries (T-085d). */
import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import type { Schema } from '../api/client';
import type { RunsPage } from '../api/hooks';
import { getConfig } from './config';
import { EVENT_TYPES, type SseClient, type SseEvent, type Unsubscribe } from './sse';

export const EVENT_QUERIES: Record<(typeof EVENT_TYPES)[number], readonly string[]> = {
  'campaign.updated': ['campaigns'],
  'run.started': ['campaigns', 'runs'],
  'run.finished': ['campaigns', 'runs'],
  'mode.discovered': ['modes', 'importance', 'risk'],
  'analysis.finished': ['modes', 'importance', 'risk'],
  'worker.updated': ['workers'],
  alert: ['alerts'],
  resync: ['campaigns'],
};
export function applyServerEvent(client: QueryClient, event: SseEvent): void {
  const campaignId = event.data['campaign_id'];
  const cid = typeof campaignId === 'string' ? campaignId : undefined;
  if (event.type === 'campaign.updated' && cid) {
    client.setQueryData<Schema['CampaignOut']>(['campaigns', cid], (old) =>
      old
        ? {
            ...old,
            ...event.data,
            counts: { ...old.counts, ...numericCounts(event.data['counts']) },
          }
        : old,
    );
    void client.invalidateQueries({ queryKey: ['campaigns', cid, 'progress'] });
    void client.invalidateQueries({ queryKey: ['campaigns'], exact: true });
    void client.invalidateQueries({ queryKey: ['campaigns', 'list'] });
  } else if (event.type === 'run.finished' || event.type === 'run.started') {
    const run = event.data['run'];
    if (
      cid &&
      typeof run === 'object' &&
      run !== null &&
      'id' in run &&
      'campaign_id' in run &&
      'ordinal' in run &&
      'scenario' in run
    ) {
      const complete = run as Schema['RunOut'];
      client.setQueriesData<InfiniteData<RunsPage>>(
        {
          queryKey: ['campaigns', cid, 'runs'],
          predicate: (query) => {
            const filters = query.queryKey[3];
            return (
              typeof filters === 'object' &&
              filters !== null &&
              Object.entries(filters).every(
                ([key, value]) => key === 'sort' && value === '-ordinal',
              ) &&
              'sort' in filters
            );
          },
        },
        (old) =>
          old
            ? {
                ...old,
                pages: old.pages.map((page, index) => ({
                  ...page,
                  items:
                    index === 0
                      ? [complete, ...page.items.filter((item) => item.id !== complete.id)]
                      : page.items.filter((item) => item.id !== complete.id),
                })),
              }
            : old,
      );
    }
    if (cid) {
      void client.invalidateQueries({ queryKey: ['campaigns', cid] });
    }
    const runId = event.data['run_id'];
    if (typeof runId === 'string') void client.invalidateQueries({ queryKey: ['runs', runId] });
  } else if (event.type === 'mode.discovered' || event.type === 'analysis.finished') {
    if (cid)
      for (const resource of EVENT_QUERIES[event.type])
        void client.invalidateQueries({ queryKey: ['campaigns', cid, resource] });
  } else if (event.type === 'worker.updated') {
    void client.invalidateQueries({ queryKey: ['workers'] });
  } else if (event.type === 'alert') {
    client.setQueryData<readonly Record<string, unknown>[]>(['alerts'], (old) =>
      [event.data, ...(old ?? [])].slice(0, getConfig().sseRecentEventLimit),
    );
  } else if (event.type === 'resync') {
    void client.invalidateQueries({ queryKey: cid ? ['campaigns', cid] : ['campaigns'] });
    void client.invalidateQueries({ queryKey: ['workers'] });
  }
}
export function bindSse(client: QueryClient, source: SseClient): Unsubscribe {
  const unsubscribe = EVENT_TYPES.map((type) =>
    source.on(type, (event) => {
      applyServerEvent(client, event);
    }),
  );
  return () => {
    unsubscribe.forEach((stop) => {
      stop();
    });
  };
}

function numericCounts(value: unknown): Record<string, number> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, number] => typeof entry[1] === 'number',
    ),
  );
}
