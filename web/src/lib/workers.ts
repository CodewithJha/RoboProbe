import type { Schema } from '../api/client';

function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function limit(meta: unknown, name: string): number | undefined {
  const value = object(object(meta)['limits'])[name];
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
}
export function isOnline(worker: Schema['WorkerOut'], timeout?: number): boolean {
  const value = object(worker);
  const age = value['heartbeat_age_s'];
  return (
    ['IDLE', 'BUSY'].includes(worker.status) &&
    (timeout === undefined || typeof age !== 'number' || age <= timeout)
  );
}
