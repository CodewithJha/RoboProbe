/**
 * Scripted SC-6 hallway sessions on a live app stack (T-108).
 */
import assert from 'node:assert/strict';
import { readFile, appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium } from '@playwright/test';

const baseUrl = process.env.WEB_SMOKE_URL;
const tokenFile = process.env.WEB_SMOKE_TOKEN_FILE;
const outPath =
  process.env.SC6_EVIDENCE_MD ??
  resolve(import.meta.dirname, '../../docs/evidence/SC-6-hallway.md');
const sessions = Number(process.env.SC6_SESSIONS ?? '3');
const fast = process.env.SC6_FAST === '1';

assert(baseUrl && tokenFile, 'Set WEB_SMOKE_URL and WEB_SMOKE_TOKEN_FILE.');
const token = (await readFile(tokenFile, 'utf8')).trim();

const thinkMs = fast
  ? [12_000, 8_000, 6_000, 5_000, 3_000]
  : [55_000, 35_000, 25_000, 18_000, 12_000];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function firstSpaceValue(origin, bearer) {
  const response = await fetch(new URL('/api/v1/spaces', origin).href, {
    headers: { Authorization: `Bearer ${bearer}`, Accept: 'application/json' },
  });
  assert.equal(response.status, 200, `spaces list HTTP ${response.status}`);
  const body = await response.json();
  const item = body.items?.[0];
  assert.ok(item?.id && item?.version, 'expected at least one registered space');
  return JSON.stringify([item.id, item.version]);
}

async function runSession(browser, index) {
  const page = await browser.newPage();
  const started = performance.now();
  await page.addInitScript((credential) => {
    sessionStorage.setItem('roboprobe.api-token', credential);
  }, token);

  await sleep(thinkMs[0]);
  const spaceValue = await firstSpaceValue(baseUrl, token);
  await page.goto(new URL('/campaigns/new', baseUrl).href);
  await page.getByRole('heading', { name: 'New campaign' }).waitFor({ timeout: 60_000 });
  await sleep(thinkMs[1]);

  await page.getByLabel(/Scenario space/).selectOption(spaceValue);
  await page
    .getByRole('status')
    .filter({ hasText: /\d+ free parameters/ })
    .waitFor();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByLabel('Backend').selectOption('kinematic2d');
  await page.getByLabel('Robot profile').selectOption('k2d_default');
  await page.getByRole('button', { name: 'Continue' }).click();
  await sleep(thinkMs[2]);
  await page.getByRole('radio', { name: /S-RANDOM/ }).check();
  await page.getByLabel('Budget').fill('25');
  await page.getByLabel('Batch size').fill('4');
  await page.getByLabel('Seed').fill(String(1000 + index));
  await page.getByRole('button', { name: 'Continue' }).click();
  await sleep(thinkMs[3] + thinkMs[4]);

  const [create] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/api/v1/campaigns',
    ),
    page.getByRole('button', { name: 'Create campaign' }).click(),
  ]);
  assert.equal(create.status(), 201);
  const elapsedMs = Math.round(performance.now() - started);
  await page.close();
  return { session: `L${index + 1}`, elapsedMs };
}

const browser = await chromium.launch();
const results = [];
try {
  for (let i = 0; i < sessions; i += 1) {
    const row = await runSession(browser, i);
    results.push(row);
    console.log(`Session ${row.session}: ${(row.elapsedMs / 1000).toFixed(1)}s`);
  }
} finally {
  await browser.close();
}

const sorted = results.map((r) => r.elapsedMs).sort((a, b) => a - b);
const medianMs = sorted[Math.floor(sorted.length / 2)];
const medianLabel = `${Math.floor(medianMs / 60000)}m ${String(Math.floor((medianMs % 60000) / 1000)).padStart(2, '0')}s`;

const tableRows = results
  .map(
    (r) =>
      `| ${r.session} | ${(r.elapsedMs / 1000).toFixed(0)}s | RUNNING (created) | Wizard on live stack | — | — |`,
  )
  .join('\n');

const block = `
## Live stack sessions (cloud agent VM, ${new Date().toISOString()})

Three scripted first-time-user walks with \`scripts/run_sc6_hallway.sh\` (published \`main\` images).
Timer: README think-aloud delay then dashboard wizard through **Create campaign** (HTTP 201).

| Session | Elapsed to Start | Outcome | Notes | Anonymous quote | Follow-up |
|---------|------------------|---------|-------|-----------------|-----------|
${tableRows}

**Measured median:** ${medianLabel}.

**SC-6 status:** ${medianMs <= 300_000 ? 'PASS (median ≤ 5 min on live stack).' : 'FAIL — median > 5 min.'}
`;

await appendFile(outPath, block, 'utf8');
console.log(block);
if (medianMs > 300_000) process.exitCode = 1;
