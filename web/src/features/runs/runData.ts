/** Safely read optional manifest and trace extension fields. */
export function object(value: unknown): Readonly<Record<string, unknown>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function number(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
export function label(value: unknown): string {
  return ['number', 'string', 'boolean'].includes(typeof value) ? String(value) : '—';
}
export function seconds(from: string | null | undefined, to: string | null | undefined): string {
  if (!from || !to) return '—';
  const duration = (Date.parse(to) - Date.parse(from)) / 1000;
  return Number.isFinite(duration) && duration >= 0 ? `${duration.toFixed(2)} s` : '—';
}
export function replayCommand(runId: string, repeats: number, fresh: boolean): string {
  if (
    !/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/iu.test(runId) ||
    !Number.isSafeInteger(repeats) ||
    repeats < 1
  )
    throw new Error('Invalid replay arguments');
  return `roboprobe replay ${runId} --repeats ${String(repeats)}${fresh ? ' --fresh-seeds' : ''}`;
}
