/** Worker heartbeat age from an ISO timestamp [s]. */
export function heartbeatAgeSeconds(last: string | null | undefined, now = Date.now()): number | undefined {
  if (!last) return undefined;
  const stamp = Date.parse(last);
  if (Number.isNaN(stamp)) return undefined;
  return Math.max(0, (now - stamp) / 1000);
}