/** Explicit reconnect/resume with bounded duplicate suppression (T-085d). */
import { getConfig, type RuntimeConfig } from './config';
import { getToken } from './token';
export type SseStatus = 'connecting' | 'open' | 'closed';
export type Unsubscribe = () => void;
export interface SseEvent {
  type: string;
  data: Record<string, unknown>;
  id: string;
}
export const EVENT_TYPES = [
  'campaign.updated',
  'run.started',
  'run.finished',
  'mode.discovered',
  'analysis.finished',
  'worker.updated',
  'alert',
  'resync',
] as const;
type EventSourceFactory = (url: string) => EventSource;
export class SseClient {
  status: SseStatus = 'closed';
  private source: EventSource | undefined;
  private reconnect: ReturnType<typeof setTimeout> | undefined;
  private attempt = 0;
  private campaignId: string | undefined;
  private resume = '';
  private stopped = true;
  private recent = new Set<string>();
  private listeners = new Map<string, Set<(event: SseEvent) => void>>();
  private statusListeners = new Set<() => void>();
  constructor(
    private readonly config: RuntimeConfig = getConfig(),
    private readonly factory: EventSourceFactory = (url) => new EventSource(url),
    private readonly random: () => number = Math.random,
  ) {}
  subscribe = (listener: () => void): Unsubscribe => {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  };
  snapshot = (): SseStatus => this.status;
  on(type: string, handler: (event: SseEvent) => void): Unsubscribe {
    const group = this.listeners.get(type) ?? new Set();
    group.add(handler);
    this.listeners.set(type, group);
    return () => group.delete(handler);
  }
  connect(campaignId?: string): void {
    this.disconnect();
    if (campaignId !== this.campaignId) {
      this.resume = '';
      this.recent.clear();
    }
    this.campaignId = campaignId;
    this.stopped = false;
    this.attempt = 0;
    this.open();
  }
  disconnect(): void {
    this.stopped = true;
    this.source?.close();
    this.source = undefined;
    clearTimeout(this.reconnect);
    this.change('closed');
  }
  private change(status: SseStatus): void {
    this.status = status;
    this.statusListeners.forEach((listener) => {
      listener();
    });
  }
  private open(): void {
    if (this.stopped) return;
    this.change('connecting');
    const url = new URL(this.config.sseUrl, window.location.href);
    if (this.campaignId) url.searchParams.set('campaign_id', this.campaignId);
    if (this.resume) url.searchParams.set('last_event_id', this.resume);
    const token = getToken();
    if (token) url.searchParams.set('token', token);
    const source = this.factory(url.href);
    this.source = source;
    source.onopen = () => {
      if (source !== this.source) return;
      this.attempt = 0;
      this.change('open');
    };
    source.onerror = () => {
      if (source === this.source) this.retry();
    };
    for (const type of EVENT_TYPES)
      source.addEventListener(type, (event) => {
        if (source !== this.source) return;
        const message = event as MessageEvent<string>;
        let data: unknown;
        try {
          data = JSON.parse(message.data) as unknown;
        } catch {
          return;
        }
        if (typeof data !== 'object' || data === null || Array.isArray(data)) return;
        const id = message.lastEventId;
        if (
          id &&
          (this.recent.has(id) ||
            (/^\d+$/.test(id) && /^\d+$/.test(this.resume) && BigInt(id) <= BigInt(this.resume)))
        )
          return;
        if (id) {
          this.resume = id;
          this.recent.add(id);
          if (this.recent.size > this.config.sseRecentEventLimit) {
            const first = this.recent.values().next().value;
            if (first !== undefined) this.recent.delete(first);
          }
        }
        this.listeners.get(type)?.forEach((handler) => {
          handler({ type, data: data as Record<string, unknown>, id });
        });
      });
  }
  private retry(): void {
    this.source?.close();
    this.source = undefined;
    if (this.stopped) return;
    this.change('connecting');
    const base = Math.min(
      this.config.sseReconnectMaxMs,
      this.config.sseReconnectInitialMs * 2 ** this.attempt++,
    );
    const delay = Math.min(
      this.config.sseReconnectMaxMs,
      base * (1 + this.random() * this.config.sseReconnectJitter),
    );
    clearTimeout(this.reconnect);
    this.reconnect = setTimeout(() => {
      this.open();
    }, delay);
  }
}
