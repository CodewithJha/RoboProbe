import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import config from './e2e.config.json' with { type: 'json' };

export async function expectNoA11yViolations(
  page: Page,
  options?: { include?: string; exclude?: string; disableRules?: string[] },
): Promise<void> {
  let builder = new AxeBuilder({ page });
  if (options?.include) {
    builder = builder.include(options.include);
  }
  if (options?.exclude) {
    builder = builder.exclude(options.exclude);
  }
  if (options?.disableRules?.length) {
    builder = builder.disableRules(options.disableRules);
  }
  builder = builder.disableRules(['color-contrast']);
  const results = await builder.analyze();
  const bad = results.violations.filter((item) =>
    config.a11y.axeImpactLevels.includes(item.impact ?? ''),
  );
  if (bad.length) {
    throw new Error(
      `axe found ${String(bad.length)} serious/critical violation(s): ${bad
        .map((item) => item.id)
        .join(', ')}`,
    );
  }
}
