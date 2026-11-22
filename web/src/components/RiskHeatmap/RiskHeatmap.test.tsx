import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { expect, it, vi } from 'vitest';
import type { Schema } from '../../api/client';
import { RiskHeatmap } from './RiskHeatmap';

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

it('keeps markers and hit targets in the same coordinate system', () => {
  const onCellClick = vi.fn();
  const { container } = render(<RiskHeatmap slice={fixture} onCellClick={onCellClick} />);
  const target = screen.getByText('1, 2: 10.0% probability of failure').parentElement;
  if (!target) throw new Error('Expected a clickable cell');
  fireEvent.click(target);
  expect(onCellClick).toHaveBeenCalledWith({ x: 1, y: 2 });
  expect(container.querySelectorAll('svg circle')).toHaveLength(1);
  expect(container.querySelector('svg path[d^="M445 "]')).toBeInTheDocument();
  expect(container.querySelectorAll('svg rect[pointer-events="none"]')).toHaveLength(2);
});

it('renders a passive thumbnail with neither probe targets nor run markers', () => {
  const { container } = render(<RiskHeatmap slice={fixture} size="thumb" />);
  expect(container.querySelector('svg')).toBeInTheDocument();
  expect(container.querySelector('svg title')).toBeNull();
  expect(container.querySelector('svg circle')).toBeNull();
  expect(screen.queryByText('Risk data table')).toBeNull();
});
