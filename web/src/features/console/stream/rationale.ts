import type { Schema } from '../../../api/client';

export function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function prediction(rationale: Record<string, unknown>): string {
  const mean = rationale['predicted_mean'];
  const deviation = rationale['predicted_std'];
  return typeof mean === 'number'
    ? `${mean.toFixed(2)}${typeof deviation === 'number' ? ` ± ${deviation.toFixed(2)}` : ''}`
    : '';
}

export function rationaleFor(run: Schema['RunOut']) {
  return { ...run.proposal, ...record(run.proposal?.['selection_rationale']) };
}
