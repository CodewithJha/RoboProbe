import { describe, expect, it } from 'vitest';

import {
  formatA12,
  formatConfig,
  formatDuration,
  formatLux,
  formatPValue,
  formatRelative,
  formatValue,
} from './format';

/** Formatters use a non-breaking space between value and unit; tests write it as a plain space. */
const plain = (text: string): string => text.replace(/\u00a0/g, ' ');
const EN = { locale: 'en-US' };
const DE = { locale: 'de-DE' };

describe('formatValue', () => {
  it.each([
    [1.25, 'm/s', {}, '1.25 m/s'],
    [3, 'm', {}, '3 m'],
    [120, 'ms', {}, '120 ms'],
    [0.123456, 'm', { precision: 4 }, '0.1235 m'],
    [1234.5, 'm', {}, '1,234.5 m'],
    [0.35, 'probability', {}, '0.35'],
    [2, '-', {}, '2'],
    [800, 'lux', {}, '800 lx'],
    [Number.NaN, 'm', {}, formatConfig.missing],
    [Number.POSITIVE_INFINITY, 'm/s', {}, formatConfig.missing],
  ])('%s %s %j → %s', (value, unit, options, expected) => {
    expect(plain(formatValue(value, unit, { ...EN, ...options }))).toBe(expected);
  });

  it('applies the Settings locale (de-DE decimal comma and grouping)', () => {
    expect(plain(formatValue(1234.5, 'm', DE))).toBe('1.234,5 m');
    expect(plain(formatValue(0.75, 'm/s', DE))).toBe('0,75 m/s');
  });

  it('never wraps a value away from its unit', () => {
    expect(formatValue(1, 'm', EN)).toBe('1\u00a0m');
  });
});

describe('formatLux', () => {
  it.each([
    [1234, '1,200 lx'],
    [0.347, '0.35 lx'],
    [5, '5 lx'],
    [Number.NaN, formatConfig.missing],
  ])('%s → %s', (value, expected) => {
    expect(plain(formatLux(value, EN))).toBe(expected);
  });

  it('uses the locale', () => {
    expect(plain(formatLux(0.347, DE))).toBe('0,35 lx');
  });
});

describe('formatDuration', () => {
  it.each([
    [0, '0 ms'],
    [850, '850 ms'],
    [999.6, '1,000 ms'],
    [1000, '1 s'],
    [12_500, '12.5 s'],
    [185_000, '3 m 05 s'],
    [3_720_000, '1 h 02 m'],
    [90_000_000, '25 h 00 m'],
    [-1, formatConfig.missing],
    [Number.NaN, formatConfig.missing],
  ])('%s ms → %s', (ms, expected) => {
    expect(plain(formatDuration(ms, EN))).toBe(expected);
  });

  it('uses the locale for fractional seconds', () => {
    expect(plain(formatDuration(12_500, DE))).toBe('12,5 s');
  });
});

describe('formatRelative', () => {
  const now = new Date('2026-11-20T12:00:00Z');
  const at = (offsetSeconds: number): Date => new Date(now.getTime() + offsetSeconds * 1000);

  it.each([
    [0, 'now'],
    [-30, '30 seconds ago'],
    [-180, '3 minutes ago'],
    [2 * 3600, 'in 2 hours'],
    [-86_400, 'yesterday'],
    [-3 * 86_400, '3 days ago'],
    [14 * 86_400, 'in 2 weeks'],
    [-60 * 86_400, '2 months ago'],
    [-400 * 86_400, 'last year'],
  ])('%s s → %s', (offset, expected) => {
    expect(formatRelative(at(offset), now, EN)).toBe(expected);
  });

  it('uses the locale', () => {
    expect(formatRelative(at(-180), now, DE)).toBe('vor 3 Minuten');
  });

  it('returns the missing marker for invalid dates', () => {
    expect(formatRelative(new Date(Number.NaN), now, EN)).toBe(formatConfig.missing);
  });
});

describe('formatPValue', () => {
  it.each([
    [0.04321, '0.043'],
    [1, '1.000'],
    [0.001, '0.001'],
    [0.000_01, '< 0.001'],
    [0, '< 0.001'],
  ])('%s → %s', (p, expected) => {
    expect(plain(formatPValue(p, EN))).toBe(expected);
  });

  it('uses the locale', () => {
    expect(plain(formatPValue(0.0001, DE))).toBe('< 0,001');
  });

  it.each([-0.1, 1.5, Number.NaN])('rejects %s', (p) => {
    expect(() => formatPValue(p)).toThrow(RangeError);
  });
});

describe('formatA12', () => {
  it.each([
    [0.714, 'medium', '0.71 (medium)'],
    [0.5, '  negligible ', '0.50 (negligible)'],
    [1, '', '1.00'],
  ])('%s %j → %s', (a12, verbal, expected) => {
    expect(formatA12(a12, verbal, EN)).toBe(expected);
  });

  it('uses the locale', () => {
    expect(formatA12(0.714, 'mittel', DE)).toBe('0,71 (mittel)');
  });

  it.each([-0.01, 1.01, Number.NaN])('rejects %s', (a12) => {
    expect(() => formatA12(a12, 'large')).toThrow(RangeError);
  });
});
