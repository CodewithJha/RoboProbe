import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { InsightsPanel } from './InsightsPanel';

vi.mock('../../../components/charts/plotlyBundle', () => ({
  default: ({ data }: { data: { type: string }[] }) => <span>{data[0]?.type} chart</span>,
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
test('displays SHAP ranks, interactions and low-confidence evidence, and switches per mode', async () => {
  vi.stubGlobal('fetch', () =>
    Response.json({
      campaign_id: 'campaign-a',
      importance: {
        names: ['speed', 'noise'],
        mean_abs_shap: [0.5, 0.3],
        gp_normalized: [0.2, 0.8],
        interactions: [
          [0.5, 0.1],
          [0.1, 0.3],
        ],
        per_mode: { 'FM-01': [0.1, 0.9] },
        auc_mean: 0.54,
        auc_std: 0.12,
        low_confidence: true,
        disagreement: ['speed'],
      },
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InsightsPanel campaignId="campaign-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText('Low confidence.')).toBeVisible();
  expect(screen.getByText('Highest SHAP importance: speed, noise.')).toBeVisible();
  expect(screen.getByText('Disagreement')).toBeVisible();
  expect(await screen.findByText('heatmap chart')).toBeVisible();
  fireEvent.change(screen.getByRole('combobox', { name: 'Importance scope' }), {
    target: { value: 'FM-01' },
  });
  expect(screen.getByText('Highest SHAP importance: noise, speed.')).toBeVisible();
});
