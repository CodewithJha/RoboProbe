/** Generated-path client, bearer auth, response ETags and RFC 9457 errors (T-085c). */
import createClient from 'openapi-fetch';
import type { components, paths } from './schema';
import { getConfig } from '../lib/config';
import { getToken } from '../lib/token';

export type Schema = components['schemas'];
export class ProblemError extends Error {
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly traceId: string | undefined;
  readonly errors: readonly Schema['FieldError'][];
  constructor(
    readonly status: number,
    problem: unknown,
  ) {
    const p =
      typeof problem === 'object' && problem !== null ? (problem as Record<string, unknown>) : {};
    const detail =
      typeof p['detail'] === 'string' ? p['detail'] : 'The request could not be completed.';
    super(detail);
    this.name = 'ProblemError';
    this.title = typeof p['title'] === 'string' ? p['title'] : 'Request failed';
    this.detail = detail;
    this.code = typeof p['code'] === 'string' ? p['code'] : 'HTTP_ERROR';
    this.traceId = typeof p['trace_id'] === 'string' ? p['trace_id'] : undefined;
    this.errors = Array.isArray(p['errors']) ? (p['errors'] as unknown[]).filter(isFieldError) : [];
  }
}
function isFieldError(value: unknown): value is Schema['FieldError'] {
  return (
    typeof value === 'object' &&
    value !== null &&
    'pointer' in value &&
    typeof value.pointer === 'string' &&
    'detail' in value &&
    typeof value.detail === 'string'
  );
}
const etags = new Map<string, string>();
export function apiUrl(path: string): string {
  const base = getConfig().apiBaseUrl.replace(/\/$/, '');
  return new URL(
    `${base}/${path.replace(/^\/api\/v1\/?/, '').replace(/^\//, '')}`,
    window.location.href,
  ).href;
}
export function getEtag(path: string): string | undefined {
  return etags.get(apiUrl(path));
}
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (input: Request) => fetch(input),
});
api.use({
  onRequest({ request }) {
    const schemaUrl = new URL(request.url);
    const target = new Request(`${apiUrl(schemaUrl.pathname)}${schemaUrl.search}`, request);
    const token = getToken();
    if (token) target.headers.set('Authorization', `Bearer ${token}`);
    const etag = etags.get(target.url);
    if (target.method === 'PATCH' && etag && !target.headers.has('If-Match'))
      target.headers.set('If-Match', etag);
    return target;
  },
  async onResponse({ request, response }) {
    const etag = response.headers.get('etag');
    if (etag) etags.set(request.url, etag);
    if (!response.ok) {
      let problem: unknown;
      try {
        problem = (await response.clone().json()) as unknown;
      } catch {
        problem = undefined;
      }
      throw new ProblemError(response.status, problem);
    }
    return response;
  },
});
export function requireData<T>(result: { data?: T }): T {
  if (result.data === undefined) throw new Error('API returned an empty response');
  return result.data;
}
