import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { contrastRatio, parseHexColour } from './contrast';
import rawTokens from './tokens.json';
import rawPairs from './tokens.pairs.json';
import { parseTokens, renderTokensCss, THEMES, type ThemeName } from './tokens';

const tokens = parseTokens(rawTokens);
// Read from disk: Vitest stubs CSS imports, including `?raw`.
const tokensCss = readFileSync(resolve(import.meta.dirname, 'tokens.css'), 'utf8');
const CATEGORIES = ['text', 'ui', 'redundant'] as const;
type Category = (typeof CATEGORIES)[number];
type Pair = readonly [string, string];
const pairs = rawPairs as unknown as Record<Category, Pair[]> & {
  minimumRatio: Record<Category, number>;
};

function colour(theme: ThemeName, token: string): ReturnType<typeof parseHexColour> {
  const value = tokens.themes[theme][token];
  if (value === undefined) {
    throw new Error(`Unknown ${theme} token ${token}`);
  }
  return parseHexColour(value);
}

const cases = THEMES.flatMap((theme) =>
  CATEGORIES.flatMap((category) =>
    pairs[category].map(([fg, bg]) => ({ theme, category, fg, bg })),
  ),
);

describe('token contrast (NFR-ACC-001)', () => {
  it('declares the WCAG AA thresholds', () => {
    expect(pairs.minimumRatio.text).toBe(4.5);
    expect(pairs.minimumRatio.ui).toBe(3);
  });

  it.each(cases)(
    '$theme: $fg on $bg meets the $category minimum',
    ({ theme, category, fg, bg }) => {
      const ratio = contrastRatio(colour(theme, fg), colour(theme, bg));
      expect(ratio).toBeGreaterThanOrEqual(pairs.minimumRatio[category]);
    },
  );

  it('checks every text colour against every surface', () => {
    const textPairs = new Set(pairs.text.map(([fg, bg]) => `${fg} ${bg}`));
    for (const fg of ['--ink', '--ink-muted', '--accent']) {
      for (const bg of ['--paper', '--paper-raised']) {
        expect(textPairs).toContain(`${fg} ${bg}`);
      }
    }
  });
});

describe('tokens.css', () => {
  it('is exactly what tokens.json renders to (run `pnpm gen:tokens`)', () => {
    expect(renderTokensCss(tokens)).toBe(tokensCss);
  });

  it('matches the snapshot', () => {
    expect(tokensCss).toMatchSnapshot();
  });

  it('defaults to the OS scheme and lets data-theme override it', () => {
    expect(tokensCss).toContain('@media (prefers-color-scheme: dark)');
    expect(tokensCss).toContain(":root:not([data-theme='light'])");
    expect(tokensCss).toContain(":root[data-theme='dark']");
  });
});

describe('parseTokens', () => {
  const minimal = { light: { '--ink': '#000000' }, dark: { '--ink': '#FFFFFF' } };

  it('splits theme and shared groups', () => {
    const parsed = parseTokens({ ...minimal, space: { '--space-1': '4px' } });
    expect(parsed.themes.dark).toEqual({ '--ink': '#FFFFFF' });
    expect(parsed.shared).toEqual({ space: { '--space-1': '4px' } });
  });

  it.each([
    ['a non-object file', [], /JSON object/],
    ['a missing theme', { light: minimal.light }, /'dark' must be an object/],
    ['mismatched themes', { ...minimal, dark: { '--paper': '#000000' } }, /same tokens/],
    ['a bad property name', { ...minimal, space: { space1: '4px' } }, /custom property/],
    ['an empty value', { ...minimal, space: { '--space-1': ' ' } }, /non-empty string/],
    ['a duplicate token', { ...minimal, font: { '--ink': 'x' } }, /more than once/],
  ])('rejects %s', (_label, raw, message) => {
    expect(() => parseTokens(raw)).toThrow(message);
  });
});
