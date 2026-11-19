/**
 * Locale-aware display formatting shared by every screen (doc 13 §4–5).
 *
 * Every function takes an optional `locale` (the Settings number-formatting choice; `undefined` means the
 * browser default) and returns display text only. Tunables live in {@link formatConfig}.
 */

/**
 * A parameter unit as carried by `ParameterSpec.unit` in the API (doc 05 §3), e.g. `m`, `m/s`, `lux`,
 * `ms`, `probability` or `-`. It is a free-form string server-side, so this stays `string` until the
 * generated OpenAPI client (T-085c) provides a narrower type.
 */
export type Unit = string;

export interface FormatOptions {
  /** Maximum fraction digits; defaults to {@link formatConfig.defaultPrecision}. */
  readonly precision?: number;
  /** BCP 47 locale from Settings; `undefined` uses the browser default. */
  readonly locale?: string | undefined;
}

/** Display tunables (no inline magic numbers in the formatters). */
export interface FormatConfig {
  readonly defaultPrecision: number;
  /** Lux spans orders of magnitude (log axis), so it is shown with significant digits instead. */
  readonly luxSignificantDigits: number;
  /** p-values below this are shown as `< floor`. */
  readonly pValueFloor: number;
  readonly pValueFractionDigits: number;
  readonly a12FractionDigits: number;
  /** Fraction digits for durations in seconds below one minute. */
  readonly secondsFractionDigits: number;
  /** Units displayed without a suffix. */
  readonly unitless: readonly Unit[];
  /** Display symbol for units whose API name is not the SI symbol. */
  readonly unitSymbols: Readonly<Record<Unit, string>>;
  /** Text shown for values that cannot be formatted (NaN, ±Infinity). */
  readonly missing: string;
}

export const formatConfig: FormatConfig = {
  defaultPrecision: 2,
  luxSignificantDigits: 2,
  pValueFloor: 0.001,
  pValueFractionDigits: 3,
  a12FractionDigits: 2,
  secondsFractionDigits: 1,
  unitless: ['', '-', 'probability'],
  unitSymbols: { lux: 'lx' },
  missing: '—',
};

/** Non-breaking space, so a value never wraps away from its unit. */
const NBSP = '\u00a0';
const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const MS_PER_MINUTE = MS_PER_SECOND * SECONDS_PER_MINUTE;
const MS_PER_HOUR = MS_PER_MINUTE * MINUTES_PER_HOUR;
const TWO_DIGITS = 2;

function withUnit(text: string, unit: Unit): string {
  if (formatConfig.unitless.includes(unit)) {
    return text;
  }
  return `${text}${NBSP}${formatConfig.unitSymbols[unit] ?? unit}`;
}

function decimal(value: number, fractionDigits: number, locale?: string, fixed = false): string {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: fractionDigits,
    minimumFractionDigits: fixed ? fractionDigits : 0,
  }).format(value);
}

/** Formats an illuminance with significant digits, suited to log-scaled values (`1,200 lx`, `0.35 lx`). */
export function formatLux(value: number, options: Pick<FormatOptions, 'locale'> = {}): string {
  if (!Number.isFinite(value)) {
    return formatConfig.missing;
  }
  const text = new Intl.NumberFormat(options.locale, {
    maximumSignificantDigits: formatConfig.luxSignificantDigits,
  }).format(value);
  return withUnit(text, 'lux');
}

/** Formats a physical value with its unit (`1.25 m/s`, `3 m`, `120 ms`); `lux` uses {@link formatLux}. */
export function formatValue(value: number, unit: Unit, options: FormatOptions = {}): string {
  if (unit === 'lux') {
    return formatLux(value, options);
  }
  if (!Number.isFinite(value)) {
    return formatConfig.missing;
  }
  const precision = options.precision ?? formatConfig.defaultPrecision;
  return withUnit(decimal(value, precision, options.locale), unit);
}

/** Formats an elapsed time: `850 ms`, `12.5 s`, `3 m 05 s`, `1 h 02 m`. */
export function formatDuration(ms: number, options: Pick<FormatOptions, 'locale'> = {}): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return formatConfig.missing;
  }
  const wholeMs = Math.round(ms);
  if (wholeMs < MS_PER_SECOND) {
    return `${String(wholeMs)}${NBSP}ms`;
  }
  // Pick the band by the value as displayed, so 59,999 ms reads `1 m 00 s`, never `60 s`.
  const scale = 10 ** formatConfig.secondsFractionDigits;
  const shownSeconds = Math.round((ms / MS_PER_SECOND) * scale) / scale;
  if (shownSeconds < SECONDS_PER_MINUTE) {
    return `${decimal(shownSeconds, formatConfig.secondsFractionDigits, options.locale)}${NBSP}s`;
  }
  const pad = (n: number): string => String(n).padStart(TWO_DIGITS, '0');
  if (ms < MS_PER_HOUR) {
    const totalSeconds = Math.max(Math.floor(ms / MS_PER_SECOND), SECONDS_PER_MINUTE);
    const minutes = Math.floor(totalSeconds / SECONDS_PER_MINUTE);
    return `${String(minutes)}${NBSP}m ${pad(totalSeconds % SECONDS_PER_MINUTE)}${NBSP}s`;
  }
  const totalMinutes = Math.floor(ms / MS_PER_MINUTE);
  const hours = Math.floor(totalMinutes / MINUTES_PER_HOUR);
  return `${String(hours)}${NBSP}h ${pad(totalMinutes % MINUTES_PER_HOUR)}${NBSP}m`;
}

/** Largest-first units for relative times, with their length in seconds. */
const SECONDS_PER_HOUR = SECONDS_PER_MINUTE * MINUTES_PER_HOUR;
const HOURS_PER_DAY = 24;
const SECONDS_PER_DAY = SECONDS_PER_HOUR * HOURS_PER_DAY;
/** Calendar approximations: relative times are coarse by design. */
const DAYS_PER_WEEK = 7;
const DAYS_PER_MONTH = 30;
const DAYS_PER_YEAR = 365;
const RELATIVE_UNITS: readonly (readonly [Intl.RelativeTimeFormatUnit, number])[] = [
  ['year', DAYS_PER_YEAR * SECONDS_PER_DAY],
  ['month', DAYS_PER_MONTH * SECONDS_PER_DAY],
  ['week', DAYS_PER_WEEK * SECONDS_PER_DAY],
  ['day', SECONDS_PER_DAY],
  ['hour', SECONDS_PER_HOUR],
  ['minute', SECONDS_PER_MINUTE],
  ['second', 1],
];

/** Formats `date` relative to `now` (`3 minutes ago`, `in 2 days`, `now`) via `Intl.RelativeTimeFormat`. */
export function formatRelative(
  date: Date,
  now: Date,
  options: Pick<FormatOptions, 'locale'> = {},
): string {
  const deltaSeconds = (date.getTime() - now.getTime()) / MS_PER_SECOND;
  if (!Number.isFinite(deltaSeconds)) {
    return formatConfig.missing;
  }
  const rtf = new Intl.RelativeTimeFormat(options.locale, { numeric: 'auto' });
  for (const [unit, seconds] of RELATIVE_UNITS) {
    if (Math.abs(deltaSeconds) >= seconds) {
      return rtf.format(Math.trunc(deltaSeconds / seconds), unit);
    }
  }
  return rtf.format(0, 'second');
}

/** Formats a p-value with fixed digits, or `< 0.001` below the floor. Throws outside [0, 1]. */
export function formatPValue(p: number, options: Pick<FormatOptions, 'locale'> = {}): string {
  if (!(p >= 0 && p <= 1)) {
    throw new RangeError(`p-value must be in [0, 1], got ${String(p)}`);
  }
  const digits = formatConfig.pValueFractionDigits;
  if (p < formatConfig.pValueFloor) {
    return `<${NBSP}${decimal(formatConfig.pValueFloor, digits, options.locale, true)}`;
  }
  return decimal(p, digits, options.locale, true);
}

/**
 * Formats a Vargha–Delaney Â12 effect size with the verbal magnitude supplied by the API
 * (`0.71 (medium)`). Throws outside [0, 1].
 */
export function formatA12(
  a12: number,
  verbal: string,
  options: Pick<FormatOptions, 'locale'> = {},
): string {
  if (!(a12 >= 0 && a12 <= 1)) {
    throw new RangeError(`Â12 must be in [0, 1], got ${String(a12)}`);
  }
  const text = decimal(a12, formatConfig.a12FractionDigits, options.locale, true);
  return verbal.trim() === '' ? text : `${text} (${verbal.trim()})`;
}
