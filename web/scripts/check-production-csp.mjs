import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const { WEB_SMOKE_URL: baseUrl, WEB_SMOKE_TOKEN_FILE: tokenFile } = process.env;
assert(baseUrl && tokenFile, 'Set the dashboard URL and the path to its test credential.');
const token = (await readFile(tokenFile, 'utf8')).trim();
const id = '00000000-0000-4000-8000-000000000001';
const paths = [
  '/',
  '/campaigns',
  '/campaigns/new',
  `/campaigns/${id}/console`,
  `/campaigns/${id}/runs`,
  `/campaigns/${id}/casebook`,
  `/campaigns/${id}/atlas`,
  `/campaigns/${id}/insights`,
  `/campaigns/${id}/settings`,
  `/runs/${id}`,
  '/trials',
  `/trials/${id}`,
  `/trials/${id}/comparison`,
  '/spaces',
  '/spaces/warehouse_v1/1',
  '/workbench',
  '/reports',
  `/reports/${id}`,
  '/settings',
  '/no-such-page',
];

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const violations = [];
  await page.exposeFunction('recordPolicyViolation', (directive) => violations.push(directive));
  await page.addInitScript((credential) => {
    sessionStorage.setItem('roboprobe.api-token', credential);
    document.addEventListener('securitypolicyviolation', (event) => {
      window.recordPolicyViolation(event.violatedDirective);
    });
  }, token);
  page.on('console', (entry) => {
    if (/content security policy/i.test(entry.text())) violations.push(entry.text());
  });
  for (const path of paths) {
    const response = await page.goto(new URL(path, baseUrl).href);
    assert(response?.ok(), `Missing dashboard HTML for ${path}`);
    assert.match(response.headers()['content-security-policy'], /frame-ancestors 'none'/);
    await page.getByRole('navigation', { name: 'Main navigation' }).waitFor();
    if (path === '/campaigns/new') {
      await page.getByRole('heading', { name: 'New campaign' }).waitFor();
    }
    assert.deepEqual(violations, [], `CSP violation at ${path}`);
  }
  console.log(`Chromium rendered ${paths.length} dashboard routes under the production CSP.`);
} finally {
  await browser.close();
}
