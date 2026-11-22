import type { Schema } from '../api/client';

export interface Parameter {
  id: string;
  name: string;
  unit: string;
  type: string;
  enabled: boolean;
  low?: number;
  high?: number;
  nominal: number | string;
  choices: string[];
  scale: string;
}
function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
export function parameters(
  definition: Schema['SpaceVersion']['definition'] | undefined,
): Parameter[] {
  const list = definition?.['parameters'];
  if (!Array.isArray(list)) return [];
  return list.flatMap((raw) => {
    const item = object(raw);
    const id = text(item['id']);
    const nominal = item['nominal'];
    if (!id || (typeof nominal !== 'number' && typeof nominal !== 'string')) return [];
    return [
      {
        id,
        name: text(item['name']) || id,
        unit: text(item['unit']),
        type: text(item['type']),
        enabled: item['enabled'] !== false,
        ...(typeof item['low'] === 'number' ? { low: item['low'] } : {}),
        ...(typeof item['high'] === 'number' ? { high: item['high'] } : {}),
        nominal,
        choices: Array.isArray(item['choices'])
          ? item['choices'].filter((v): v is string => typeof v === 'string')
          : [],
        scale: text(item['scale']),
      },
    ];
  });
}
