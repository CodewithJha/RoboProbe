import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConditionStrip } from './ConditionStrip';

describe('ConditionStrip', () => {
  it('describes physical units and characteristic parameters', async () => {
    render(
      <ConditionStrip
        values={[0.9, 0.1]}
        labels={['Speed', 'Light']}
        formatted={['0.42 m/s', '12 lux']}
        highlight={[0]}
        size="sm"
      />,
    );
    const trigger = screen.getByRole('button', {
      name: /Speed: 0.42 m\/s \(characteristic\); Light: 12 lux/,
    });
    fireEvent.focus(trigger);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('12 lux');
    fireEvent.keyDown(trigger, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
  it('clamps bars and exposes unavailable values without NaN geometry', () => {
    const { container } = render(
      <ConditionStrip values={[-1, 2, Number.NaN]} labels={['Low', 'High', 'Unknown']} size="xs" />,
    );
    expect(screen.getByRole('img')).toHaveAccessibleName(
      /Low: 0%.*High: 100%.*Unknown: unavailable/,
    );
    expect(container.innerHTML).not.toContain('NaN');
  });
  it('describes an empty strip', () => {
    render(<ConditionStrip values={[]} labels={[]} size="md" />);
    expect(screen.getByRole('img')).toHaveAccessibleName('No enabled parameters');
  });
});
