import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_CONFIG } from './config';
import { SseClient } from './sse';
class Source extends EventTarget {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  emit(type: string, data: string, id = '') {
    this.dispatchEvent(new MessageEvent(type, { data, lastEventId: id }));
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
});
afterEach(() => vi.useRealTimers());
function setup() {
  const sources: Source[] = [];
  const urls: string[] = [];
  const factory = (url: string) => {
    urls.push(url);
    const source = new Source();
    sources.push(source);
    return source as unknown as EventSource;
  };
  return { sources, urls, client: new SseClient(DEFAULT_CONFIG, factory, () => 0) };
}
describe('SSE reconnect and resume', () => {
  it('resumes the last processed ID and suppresses duplicates', () => {
    const { client, sources, urls } = setup();
    const handler = vi.fn();
    sessionStorage.setItem('roboprobe.api-token', 'session-secret');
    client.on('run.finished', handler);
    client.connect('campaign-one');
    const first = sources[0];
    if (!first) throw new Error('missing source');
    first.onopen?.();
    expect(client.status).toBe('open');
    first.emit('run.finished', '{"campaign_id":"campaign-one"}', '17');
    first.onerror?.();
    expect(first.close).toHaveBeenCalled();
    vi.advanceTimersByTime(DEFAULT_CONFIG.sseReconnectInitialMs);
    const resumed = new URL(urls[1] ?? '');
    expect(resumed.searchParams.get('last_event_id')).toBe('17');
    expect(resumed.searchParams.get('campaign_id')).toBe('campaign-one');
    expect(resumed.searchParams.get('token')).toBe('session-secret');
    sources[1]?.emit('run.finished', '{}', '17');
    sources[1]?.emit('run.finished', '{}', '18');
    expect(handler).toHaveBeenCalledTimes(2);
    client.disconnect();
    expect(client.status).toBe('closed');
    vi.runOnlyPendingTimers();
    expect(urls).toHaveLength(2);
  });
  it('clears resume state when campaign scope changes and rejects malformed events', () => {
    const { client, sources, urls } = setup();
    const handler = vi.fn();
    const stop = client.on('alert', handler);
    client.connect('one');
    sources[0]?.emit('alert', 'not-json', 'bad');
    sources[0]?.emit('alert', '[]', 'bad');
    sources[0]?.emit('alert', '{}', '10');
    stop();
    sources[0]?.emit('alert', '{}', '11');
    client.connect('two');
    expect(new URL(urls[1] ?? '').searchParams.has('last_event_id')).toBe(false);
    expect(handler).toHaveBeenCalledTimes(1);
    client.disconnect();
  });
  it('uses exponential backoff before a successful connection', () => {
    const { client, sources } = setup();
    client.connect();
    sources[0]?.onerror?.();
    vi.advanceTimersByTime(DEFAULT_CONFIG.sseReconnectInitialMs);
    sources[1]?.onerror?.();
    vi.advanceTimersByTime(DEFAULT_CONFIG.sseReconnectInitialMs);
    expect(sources).toHaveLength(2);
    vi.advanceTimersByTime(DEFAULT_CONFIG.sseReconnectInitialMs);
    expect(sources).toHaveLength(3);
    client.disconnect();
  });
});
