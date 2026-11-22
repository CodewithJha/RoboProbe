import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG, getConfig, loadConfig, parseConfig, setConfig } from './config';
afterEach(() => {
  setConfig(DEFAULT_CONFIG);
});
describe('runtime configuration', () => {
  it('loads runtime overrides and derives the SSE URL from the API address', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        apiBaseUrl: '/custom/api',
        defaultTheme: 'dark',
        featureFlags: { trials: false, reports: true },
      }),
    );
    const config = await loadConfig(fetcher);
    expect(config.apiBaseUrl).toBe('/custom/api');
    expect(config.sseUrl).toBe('/custom/api/events');
    expect(config.defaultTheme).toBe('dark');
    expect(getConfig()).toBe(config);
    expect(fetcher).toHaveBeenCalledWith('/config.json', { cache: 'no-store' });
  });
  it('uses development defaults for absent files or network failure', async () => {
    expect(
      await loadConfig(
        vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 404 })),
      ),
    ).toEqual(DEFAULT_CONFIG);
    expect(
      await loadConfig(vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'))),
    ).toEqual(DEFAULT_CONFIG);
  });
  it.each([
    { apiBaseUrl: 'javascript:alert(1)' },
    { defaultTheme: 'red' },
    { featureFlags: { trials: 'yes' } },
    { queryRetryAttempts: -1 },
    { sseReconnectJitter: 2 },
    { sseReconnectMaxMs: 1 },
  ])('rejects invalid boot data %j', (raw) => {
    expect(() => parseConfig(raw)).toThrow();
  });
  it('does not hide a server error behind development defaults', async () => {
    await expect(
      loadConfig(vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 500 }))),
    ).rejects.toThrow('500');
  });
});
