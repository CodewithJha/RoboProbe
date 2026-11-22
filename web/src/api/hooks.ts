/** Resource hooks; keys follow the API hierarchy (T-085c, FR-DSH-008). */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiUrl, ProblemError, requireData, type Schema } from './client';
import { getToken } from '../lib/token';
import type { operations } from './schema';

export type Campaign = Schema['CampaignOut'];
export type Run = Schema['RunOut'];
export type RunFilters = NonNullable<
  operations['list_runs_api_v1_campaigns__campaign_id__runs_get']['parameters']['query']
>;
export type RunsPage = Schema['Page_RunOut_'];
const nextPage = (page: { next_cursor?: string | null }): string | undefined =>
  page.next_cursor ?? undefined;

export function useCampaigns(filter?: { status?: Campaign['status']; limit?: number }) {
  return useInfiniteQuery({
    queryKey: filter ? ['campaigns', 'list', filter] : ['campaigns'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const query = { ...filter, ...(pageParam ? { cursor: pageParam } : {}) };
      return requireData(await api.GET('/api/v1/campaigns', { signal, params: { query } }));
    },
    getNextPageParam: nextPage,
  });
}
export function useCampaign(id: string) {
  return useQuery({
    queryKey: ['campaigns', id],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}', {
          signal,
          params: { path: { campaign_id: id } },
        }),
      ),
  });
}
export function useCampaignProgress(id: string) {
  return useQuery({
    queryKey: ['campaigns', id, 'progress'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/progress', {
          signal,
          params: { path: { campaign_id: id } },
        }),
      ),
  });
}
export function useRuns(id: string, filters: RunFilters = {}) {
  return useInfiniteQuery({
    queryKey: ['campaigns', id, 'runs', filters],
    enabled: Boolean(id),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/runs', {
          signal,
          params: {
            path: { campaign_id: id },
            query: { ...filters, ...(pageParam ? { cursor: pageParam } : {}) },
          },
        }),
      ),
    getNextPageParam: nextPage,
  });
}
export function useRun(id: string) {
  return useQuery({
    queryKey: ['runs', id],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/runs/{run_id}', { signal, params: { path: { run_id: id } } }),
      ),
  });
}
export function useRunArtifacts(id: string) {
  return useQuery({
    queryKey: ['runs', id, 'artifacts'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/runs/{run_id}/artifacts', {
          signal,
          params: { path: { run_id: id } },
        }),
      ),
  });
}
export function useModes(id: string) {
  return useQuery({
    queryKey: ['campaigns', id, 'modes'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/modes', {
          signal,
          params: { path: { campaign_id: id } },
        }),
      ),
  });
}
export function useMode(id: string) {
  return useQuery({
    queryKey: ['modes', id],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/modes/{mode_id}', { signal, params: { path: { mode_id: id } } }),
      ),
  });
}
export function useImportance(id: string) {
  return useQuery({
    queryKey: ['campaigns', id, 'importance'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/importance', {
          signal,
          params: { path: { campaign_id: id } },
        }),
      ),
  });
}
export function useRisk(id: string) {
  return useQuery({
    queryKey: ['campaigns', id, 'risk'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/risk', {
          signal,
          params: { path: { campaign_id: id } },
        }),
      ),
  });
}
export type SliceQuery = NonNullable<
  operations['risk_slice_api_v1_campaigns__campaign_id__risk_slice_get']['parameters']['query']
>;
export function useRiskSlice(id: string, query: SliceQuery) {
  return useQuery({
    queryKey: ['campaigns', id, 'risk', 'slice', query],
    enabled: Boolean(id && query.x && query.y),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/campaigns/{campaign_id}/risk/slice', {
          signal,
          params: { path: { campaign_id: id }, query },
        }),
      ),
  });
}
export function useExperiments() {
  return useInfiniteQuery({
    queryKey: ['experiments'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) =>
      requireData(
        await api.GET('/api/v1/experiments', {
          signal,
          params: { query: pageParam ? { cursor: pageParam } : {} },
        }),
      ),
    getNextPageParam: nextPage,
  });
}
export function useExperiment(id: string) {
  return useQuery({
    queryKey: ['experiments', id],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/experiments/{experiment_id}', {
          signal,
          params: { path: { experiment_id: id } },
        }),
      ),
  });
}
export function useExperimentComparison(id: string) {
  return useQuery({
    queryKey: ['experiments', id, 'comparison'],
    enabled: Boolean(id),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/experiments/{experiment_id}/comparison', {
          signal,
          params: { path: { experiment_id: id } },
        }),
      ),
  });
}
export function useSpaces() {
  return useInfiniteQuery({
    queryKey: ['spaces'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) =>
      requireData(
        await api.GET('/api/v1/spaces', {
          signal,
          params: { query: pageParam ? { cursor: pageParam } : {} },
        }),
      ),
    getNextPageParam: nextPage,
  });
}
export function useSpace(id: string, version: string) {
  return useQuery({
    queryKey: ['spaces', id, 'versions', version],
    enabled: Boolean(id && version),
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/spaces/{space_id}/versions/{version}', {
          signal,
          params: { path: { space_id: id, version } },
        }),
      ),
  });
}
export function useSutProfiles() {
  return useInfiniteQuery({
    queryKey: ['sut-profiles'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) =>
      requireData(
        await api.GET('/api/v1/sut-profiles', {
          signal,
          params: { query: pageParam ? { cursor: pageParam } : {} },
        }),
      ),
    getNextPageParam: nextPage,
  });
}
export function useWorkers() {
  return useQuery({
    queryKey: ['workers'],
    queryFn: async ({ signal }) => requireData(await api.GET('/api/v1/workers', { signal })),
  });
}
export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: async ({ signal }) => requireData(await api.GET('/api/v1/meta', { signal })),
  });
}
export function useReportJob(id: string, refreshInterval?: number) {
  return useQuery<Schema['ReportJobOut']>({
    queryKey: ['reports', id],
    enabled: Boolean(id),
    refetchInterval: ({ state }) => {
      if (!refreshInterval || state.error) return false;
      if (state.data && !['PENDING', 'QUEUED', 'RUNNING'].includes(state.data.status)) return false;
      return refreshInterval;
    },
    queryFn: async ({ signal }) =>
      requireData(
        await api.GET('/api/v1/reports/{report_id}', {
          signal,
          params: { path: { report_id: id } },
        }),
      ),
  });
}
export function useCreateCampaign(idempotencyKey?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      body,
      idempotencyKey: key,
    }: {
      body: Schema['CampaignCreate'];
      idempotencyKey?: string;
    }) =>
      requireData(
        await api.POST('/api/v1/campaigns', {
          body,
          headers: { 'Idempotency-Key': key ?? idempotencyKey ?? crypto.randomUUID() },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns'] }),
  });
}
const commands = {
  start: '/api/v1/campaigns/{campaign_id}:start',
  pause: '/api/v1/campaigns/{campaign_id}:pause',
  resume: '/api/v1/campaigns/{campaign_id}:resume',
  cancel: '/api/v1/campaigns/{campaign_id}:cancel',
} as const;
export function useCampaignCommand(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (command: keyof typeof commands) =>
      requireData(await api.POST(commands[command], { params: { path: { campaign_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns', id] }),
  });
}
export function usePatchCampaign(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schema['CampaignPatch']) =>
      requireData(
        await api.PATCH('/api/v1/campaigns/{campaign_id}', {
          params: { path: { campaign_id: id } },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns'] }),
  });
}
export function usePatchMode(id: string, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schema['FailureModePatch']) =>
      requireData(
        await api.PATCH('/api/v1/modes/{mode_id}', { params: { path: { mode_id: id } }, body }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['modes', id] });
      await client.invalidateQueries({ queryKey: ['campaigns', campaignId, 'modes'] });
    },
  });
}
export function useReplay(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schema['ReplayRequest']) =>
      requireData(
        await api.POST('/api/v1/runs/{run_id}:replay', { params: { path: { run_id: id } }, body }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns'] }),
  });
}
export function useManualRuns(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schema['ManualRunCreate']) =>
      requireData(
        await api.POST('/api/v1/campaigns/{campaign_id}/runs', {
          params: { path: { campaign_id: id } },
          body,
          headers: { 'Idempotency-Key': crypto.randomUUID() },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns', id] }),
  });
}
export function useAnalyze(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      requireData(
        await api.POST('/api/v1/campaigns/{campaign_id}:analyze', {
          params: { path: { campaign_id: id } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns', id] }),
  });
}
export function useCreateReport() {
  return useMutation({
    mutationFn: async (body: Schema['ReportCreate']) =>
      requireData(await api.POST('/api/v1/reports', { body })),
  });
}
export function useValidateSpace() {
  return useMutation({
    mutationFn: async (yaml: string) => {
      const headers = new Headers({ 'Content-Type': 'application/yaml' });
      const token = getToken();
      if (token) headers.set('Authorization', `Bearer ${token}`);
      const response = await fetch(apiUrl('/spaces/validate'), {
        method: 'POST',
        headers,
        body: yaml,
      });
      const payload = (await response.json()) as Schema['SpaceValidationResult'] | undefined;
      if (!response.ok) throw new ProblemError(response.status, payload);
      if (!payload) throw new Error('Validation returned an empty response');
      return payload;
    },
  });
}

export function useRunTrace(id: string, hz?: number, columns?: string) {
  return useQuery({
    queryKey: ['runs', id, 'trace', { hz, columns }],
    enabled: Boolean(id),
    queryFn: async ({ signal }): Promise<Schema['TraceOut']> => {
      const data = requireData(
        await api.GET('/api/v1/runs/{run_id}/trace', {
          signal,
          headers: { Accept: 'application/json' },
          params: {
            path: { run_id: id },
            query: { ...(hz === undefined ? {} : { hz }), ...(columns ? { columns } : {}) },
          },
        }),
      );
      if (typeof data === 'string') throw new Error('The server returned a non-JSON trace.');
      return data;
    },
  });
}
