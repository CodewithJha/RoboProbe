import { act, fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import type { PlotParams } from 'react-plotly.js';
import { expect, it, vi } from 'vitest';
import type { Schema } from '../../api/client';
import { RiskHeatmap } from './RiskHeatmap';

const chart = vi.hoisted(() => ({ read: vi.fn<(props: PlotParams) => void>() }));
vi.mock('../charts/plotlyBundle', () => ({
  default: (props: PlotParams) => {
    chart.read(props);
    return <div data-testid="plotly" />;
  },
}));

const fixture: Schema['RiskSliceOut'] = {
  anchor: 'nominal',
  resolution: 2,
  x_param: 'speed',
  y_param: 'distance',
  log_x: true,
  log_y: false,
  x_values: [1, 10],
  y_values: [2, 3],
  p_fail: [
    [0.1, 0.6],
    [0.4, 0.8],
  ],
  region: [
    [0, 1],
    [1, 2],
  ],
  points: [
    { x: 1, y: 2, verdict: 'PASS' },
    { x: 10, y: 3, verdict: 'FAIL' },
    { x: 0, y: 2, verdict: 'PASS' },
  ],
};

it('exposes physical risk coordinates through the table alternative', async () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  const onCellClick = vi.fn();
  const { container } = render(<RiskHeatmap slice={fixture} onCellClick={onCellClick} />);
  fireEvent.click(screen.getByText('Risk data table'));
  fireEvent.click(await screen.findByRole('button', { name: /Probe speed 10, distance 2/ }));
  expect(onCellClick).toHaveBeenCalledWith({ x: 10, y: 2 });
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
  expect(result.violations).toEqual([]);
});

it('plots physical axes and maps Plotly cell events to physical coordinates', async () => {
  const onCellClick = vi.fn();
  const { container } = render(<RiskHeatmap slice={fixture} onCellClick={onCellClick} />);
  await screen.findByTestId('plotly');
  const props = chart.read.mock.lastCall?.[0];
  expect(props?.layout).toMatchObject({ xaxis: { type: 'log', range: [-0.5, 1.5] } });
  expect(props?.data).toMatchObject([
    { type: 'heatmap', z: fixture.p_fail },
    {
      type: 'contour',
      contours: { start: 0.5, end: 0.5, size: 0.5, coloring: 'none' },
    },
    {
      type: 'scatter',
      x: [1],
      y: [2],
      marker: { symbol: 'circle-open' },
    },
    {
      type: 'scatter',
      x: [10],
      y: [3],
      marker: { symbol: 'x' },
    },
  ]);
  props?.onClick?.({ points: [{ curveNumber: 0, pointNumber: [0, 1] }] });
  expect(onCellClick).toHaveBeenCalledWith({ x: 10, y: 2 });
  expect(container.querySelectorAll('svg rect[pointer-events="none"]')).toHaveLength(2);
});

it('resizes Plotly with the container and preserves the normalized hatch coordinates', async () => {
  let resized: (() => void) | undefined;
  const bounds = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect');
  bounds.mockReturnValue(new DOMRect(0, 0, 600, 360));
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe() {
        resized?.();
      }
      disconnect() {
        /* test stub */
      }
    },
  );
  try {
    const { container } = render(<RiskHeatmap slice={fixture} />);
    await screen.findByTestId('plotly');
    const hatch = container.querySelector('svg rect[pointer-events="none"]');
    expect(hatch).toHaveAttribute('x', '300');
    expect(chart.read.mock.lastCall?.[0].layout).toMatchObject({ width: 600, height: 360 });
    bounds.mockReturnValue(new DOMRect(0, 0, 300, 180));
    act(() => {
      resized?.();
    });
    expect(hatch).toHaveAttribute('x', '300');
    expect(chart.read.mock.lastCall?.[0].layout).toMatchObject({ width: 300, height: 180 });
  } finally {
    vi.unstubAllGlobals();
  }
});

it('renders a passive thumbnail with neither probe targets nor run markers', async () => {
  const { container } = render(<RiskHeatmap slice={fixture} size="thumb" />);
  await screen.findByTestId('plotly');
  expect(chart.read.mock.lastCall?.[0].config).toMatchObject({ staticPlot: true });
  expect(chart.read.mock.lastCall?.[0].data).toMatchObject([
    { type: 'heatmap' },
    { type: 'contour' },
  ]);
  expect(container.querySelector('svg')).toBeInTheDocument();
  expect(container.querySelector('svg title')).toBeNull();
  expect(container.querySelector('svg circle')).toBeNull();
  expect(screen.queryByText('Risk data table')).toBeNull();
});
