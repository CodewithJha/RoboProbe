import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const {
  WEB_SMOKE_URL: baseUrl,
  WEB_SMOKE_TOKEN_FILE: tokenFile,
  WEB_SMOKE_CAMPAIGN_ID: campaignId,
  WEB_SMOKE_WORKER_COUNT: workerCount,
  WEB_SMOKE_REPORT_PATH: reportPath,
} = process.env;
assert(
  baseUrl && tokenFile && campaignId && Number(workerCount) > 0,
  'Missing quick-start inputs.',
);
const token = (await readFile(tokenFile, 'utf8')).trim();

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.addInitScript((credential) => {
    sessionStorage.setItem('roboprobe.api-token', credential);
  }, token);

  const dashboardStarted = performance.now();
  await page.goto(new URL('/workbench', baseUrl).href);
  await expect(page.getByRole('heading', { name: 'Workers' })).toBeVisible();
  const rows = page.getByRole('row').filter({ hasText: 'kinematic2d' });
  await expect(rows).toHaveCount(Number(workerCount));
  const dashboardMs = Math.round(performance.now() - dashboardStarted);
  console.log(`Workbench showed ${workerCount} registered workers after ${dashboardMs} ms.`);

  await page.goto(new URL(`/campaigns/${campaignId}/casebook`, baseUrl).href);
  await expect(page.getByRole('heading', { name: 'Casebook' })).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();
  console.log('The demo campaign produced at least one visible case.');

  await page.goto(new URL(`/campaigns/${campaignId}/console`, baseUrl).href);
  const reportStarted = performance.now();
  await page.getByRole('button', { name: 'Export report' }).click();
  await page.waitForURL(/\/reports\//);
  await expect(page.getByRole('heading', { name: 'Exported report' })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download HTML' }).click(),
  ]);
  assert.match(download.suggestedFilename(), /\.html$/);
  assert.equal(await download.failure(), null);
  if (reportPath) await download.saveAs(reportPath);
  const reportMs = Math.round(performance.now() - reportStarted);
  console.log(`Downloaded the campaign HTML report after ${reportMs} ms.`);
} finally {
  await browser.close();
}
