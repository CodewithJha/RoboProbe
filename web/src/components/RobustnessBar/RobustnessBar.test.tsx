import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RobustnessBar } from './RobustnessBar';

describe('RobustnessBar', () => {
  it.each([-2, -0.37, 0, 0.42, 2])('exposes clamped meter bounds for %s', (value) => {
    render(<RobustnessBar value={value} />);
    const meter = screen.getByRole('meter', { name: 'Robustness' });
    expect(meter).toHaveAttribute('aria-valuemin', '-1');
    expect(meter).toHaveAttribute('aria-valuemax', '1');
    expect(meter).toHaveAttribute('aria-valuenow', String(Math.max(-1, Math.min(1, value))));
  });
  it('does not misrepresent unavailable data as zero', () => {
    render(<RobustnessBar value={Number.NaN} />);
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Robustness: unavailable')).toBeInTheDocument();
  });
});
