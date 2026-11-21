import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { PropsWithChildren } from 'react';
import { api, apiUrl, ProblemError, requireData } from './client';
import { useRuns } from './hooks';
import { DEFAULT_CONFIG, setConfig } from '../lib/config';
import { setToken } from '../lib/token';
const server = setupServer();
beforeAll(() => {
  server.listen();
});
afterEach(() => {
  server.resetHandlers();
  sessionStorage.clear();
  setConfig(DEFAULT_CONFIG);
});
afterAll(() => {
  server.close();
});
describe('generated API client', () => {
  it('uses runtime URL and session bearer token', async () => {
    setConfig({ ...DEFAULT_CONFIG, apiBaseUrl: '/custom' });
    setToken('private-token');
    server.use(
      http.get(apiUrl('/meta'), ({ request }) => {
        expect(request.headers.get('authorization')).toBe('Bearer private-token');
        return HttpResponse.json({ version: 'test' });
      }),
    );
    expect(requireData(await api.GET('/api/v1/meta'))).toEqual({ version: 'test' });
    expect(localStorage.getItem('roboprobe.api-token')).toBeNull();
  });
  it('exposes structured problem details and field errors', async () => {
    server.use(
      http.get(apiUrl('/meta'), () =>
        HttpResponse.json(
          {
            code: 'SPACE_INVALID',
            title: 'Invalid space',
            detail: 'Bad high',
            trace_id: 'trace-1',
            errors: [{ pointer: '/high', detail: 'too low' }],
          },
          { status: 422 },
        ),
      ),
    );
    await expect(api.GET('/api/v1/meta')).rejects.toMatchObject({
      code: 'SPACE_INVALID',
      title: 'Invalid space',
      detail: 'Bad high',
      traceId: 'trace-1',
      errors: [{ pointer: '/high', detail: 'too low' }],
    });
  });
  it('captures ETags and sends If-Match for PATCH', async () => {
    server.use(
      http.get(apiUrl('/campaigns/c1'), () =>
        HttpResponse.json({ id: 'c1' }, { headers: { ETag: 'W/"2"' } }),
      ),
      http.patch(apiUrl('/campaigns/c1'), ({ request }) => {
        expect(request.headers.get('if-match')).toBe('W/"2"');
        return HttpResponse.json({ id: 'c1' });
      }),
    );
    await api.GET('/api/v1/campaigns/{campaign_id}', { params: { path: { campaign_id: 'c1' } } });
    await api.PATCH('/api/v1/campaigns/{campaign_id}', {
      params: { path: { campaign_id: 'c1' } },
      body: { name: 'Changed' },
    });
  });
  it('fetches the next infinite runs page with the server cursor', async () => {
    const cursors: (string | null)[] = [];
    server.use(
      http.get(apiUrl('/campaigns/c1/runs'), ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        cursors.push(cursor);
        return HttpResponse.json({
          items: [{ id: cursor ? 'r2' : 'r1' }],
          next_cursor: cursor ? null : 'cursor-2',
        });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const hook = renderHook(() => useRuns('c1'), { wrapper });
    await waitFor(() => {
      expect(hook.result.current.data?.pages).toHaveLength(1);
    });
    await act(async () => {
      const result = await hook.result.current.fetchNextPage();
      expect(result.error).toBeNull();
      expect(result.data?.pages).toHaveLength(2);
    });
    expect(cursors).toEqual([null, 'cursor-2']);
    await waitFor(() => {
      expect(hook.result.current.data?.pages).toHaveLength(2);
    });
    client.clear();
  });
  it('wraps non-JSON errors without exposing response content', () => {
    expect(new ProblemError(500, '<secret>')).toMatchObject({
      title: 'Request failed',
      code: 'HTTP_ERROR',
    });
  });
});
