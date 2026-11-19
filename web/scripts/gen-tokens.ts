/**
 * Renders `src/styles/tokens.json` to `src/styles/tokens.css` and copies the JSON to the backend report
 * theme (T-078a), so the CSS, the dashboard and the static report can never diverge.
 *
 * Usage: `pnpm gen:tokens` writes the outputs; `pnpm gen:tokens --check` writes nothing and exits 1 if
 * any output is stale (CI idempotency gate). Runs on Node >= 24 with native type stripping.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { parseArgs } from 'node:util';

import { parseTokens, renderTokensCss } from '../src/styles/tokens.ts';

const WEB_ROOT = resolve(import.meta.dirname, '..');
const REPO_ROOT = resolve(WEB_ROOT, '..');
const SOURCE = resolve(WEB_ROOT, 'src/styles/tokens.json');
const CSS_OUTPUT = resolve(WEB_ROOT, 'src/styles/tokens.css');
const REPORT_OUTPUT = resolve(REPO_ROOT, 'backend/src/roboprobe/reporting/assets/tokens.json');
const EXIT_STALE = 1;

function readOrEmpty(path: string): string {
  try {
    return readFileSync(path, 'utf8');
  } catch {
    return '';
  }
}

function main(): number {
  const { values } = parseArgs({ options: { check: { type: 'boolean', default: false } } });
  const source = readFileSync(SOURCE, 'utf8');
  const outputs = new Map([
    [CSS_OUTPUT, renderTokensCss(parseTokens(JSON.parse(source)))],
    [REPORT_OUTPUT, source],
  ]);
  const stale = [...outputs].filter(([path, content]) => readOrEmpty(path) !== content);
  for (const [path, content] of stale) {
    const shown = relative(REPO_ROOT, path);
    if (values.check) {
      console.error(`stale: ${shown} (run 'pnpm --dir web gen:tokens')`);
    } else {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, content);
      console.log(`wrote ${shown}`);
    }
  }
  return values.check && stale.length > 0 ? EXIT_STALE : 0;
}

process.exitCode = main();
