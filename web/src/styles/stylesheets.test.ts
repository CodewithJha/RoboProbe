// @vitest-environment node
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import stylelint from 'stylelint';
import { describe, expect, it } from 'vitest';

const WEB_ROOT = resolve(import.meta.dirname, '../..');
const STYLES = resolve(WEB_ROOT, 'src/styles');
const FONT_DIR = resolve(WEB_ROOT, 'public/fonts');

async function lintCss(code: string, codeFilename: string): Promise<string[]> {
  const result = await stylelint.lint({ code, codeFilename, cwd: WEB_ROOT });
  return (result.results[0]?.warnings ?? []).map((warning) => warning.rule);
}

describe('stylelint policy', () => {
  const feature = resolve(WEB_ROOT, 'src/features/example.css');

  it('rejects raw hex colours in feature CSS', async () => {
    expect(await lintCss('a {\n  color: #ff0000;\n}\n', feature)).toContain('color-no-hex');
  });

  it('rejects raw px font sizes in feature CSS', async () => {
    expect(await lintCss('a {\n  font-size: 13px;\n}\n', feature)).toContain(
      'declaration-property-unit-disallowed-list',
    );
  });

  it('accepts token references', async () => {
    const code = 'a {\n  color: var(--ink);\n  font-size: var(--font-size-sm);\n}\n';
    expect(await lintCss(code, feature)).toEqual([]);
  });

  it('allows hex values only in the generated tokens.css', async () => {
    const path = resolve(STYLES, 'tokens.css');
    expect(await lintCss(readFileSync(path, 'utf8'), path)).toEqual([]);
  });
});

describe('fonts', () => {
  const fontsCss = readFileSync(resolve(STYLES, 'fonts.css'), 'utf8');
  const urls = [...fontsCss.matchAll(/url\('([^']+)'\)/g)].map((match) => match[1] ?? '');

  it('declares self-hosted WOFF2 faces with font-display: swap', () => {
    expect(urls.length).toBeGreaterThan(0);
    expect(fontsCss.match(/font-display: swap/g)).toHaveLength(urls.length);
  });

  it.each(urls)('%s is a local file with a recorded licence', (url) => {
    expect(url).toMatch(/^\/fonts\/[\w-]+\.woff2$/);
    const file = url.replace(/^\/fonts\//, '');
    expect(existsSync(resolve(FONT_DIR, file))).toBe(true);
    expect(readFileSync(resolve(FONT_DIR, 'LICENSES.md'), 'utf8')).toContain(file);
  });
});

describe('base.css', () => {
  const base = readFileSync(resolve(STYLES, 'base.css'), 'utf8');

  it('draws the focus ring with the margin line', () => {
    expect(base).toMatch(
      /:focus-visible\s*{\s*outline: var\(--focus-ring-width\) solid var\(--margin-line\)/,
    );
  });

  it('disables transitions and animations under prefers-reduced-motion', () => {
    const reduced = base.slice(base.indexOf('@media (prefers-reduced-motion: reduce)'));
    expect(reduced).toContain('transition-duration: 0s !important');
    expect(reduced).toContain('animation-duration: 0s !important');
  });
});
