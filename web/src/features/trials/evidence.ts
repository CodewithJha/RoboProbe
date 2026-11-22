import type { Schema } from '../../api/client';

export function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function text(value: unknown): string {
  return typeof value === 'string' ? value : '—';
}

export function number(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function interval(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 2) return undefined;
  const low = number(value[0]);
  const high = number(value[1]);
  return low !== undefined && high !== undefined ? [low, high] : undefined;
}

export function strategyNames(design: Schema['ExperimentOut']['design']): string[] {
  const strategies = design['strategies'];
  return Array.isArray(strategies)
    ? strategies.flatMap((item) => {
        const strategy = asRecord(item);
        const name = strategy['label'] ?? strategy['id'];
        return typeof name === 'string' ? [name] : [];
      })
    : [];
}

export function summaries(data: Schema['ExperimentComparisonOut']) {
  return Object.entries(data.strategies ?? {}).flatMap(([strategy, statistics]) =>
    [...new Set([...(data.metrics ?? []), ...Object.keys(statistics)])].map((metric) => {
      const summary = asRecord(statistics[metric]);
      return {
        strategy,
        metric,
        median: number(summary['median']),
        iqr: interval(summary['iqr']),
        ci: interval(summary['ci95']),
      };
    }),
  );
}

export function cells(experiment: Schema['ExperimentOut']) {
  return (experiment.cells ?? []).flatMap((value) => {
    const id = value['campaign_id'];
    return typeof id === 'string' && id
      ? [
          {
            id,
            strategy: text(value['strategy_id']),
            seed: number(value['seed']),
            budget: number(value['budget']),
            status: text(value['status']),
          },
        ]
      : [];
  });
}
