import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

interface Options {
  include?: readonly string[];
  disableRules?: readonly string[];
}

export async function expectNoA11yViolations(page: Page, options: Options = {}) {
  const scan = new AxeBuilder({ page });
  for (const selector of options.include ?? []) scan.include(selector);
  if (options.disableRules?.length) scan.disableRules([...options.disableRules]);
  const { violations } = await scan.analyze();
  const serious = violations
    .filter(({ impact }) => impact === 'serious' || impact === 'critical')
    .map(({ id, impact, nodes }) => ({ id, impact, targets: nodes.map(({ target }) => target) }));
  expect(serious, 'serious or critical accessibility violations').toEqual([]);
}
