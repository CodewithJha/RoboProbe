import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Spine, type SpineRun } from './Spine';

const runs: SpineRun[] = Array.from({ length: 10000 }, (_, index) => ({
  id: `run-${String(index)}`,
  ordinal: index + 1,
  verdict: index % 2 === 0 ? 'PASS' : 'FAIL',
}));
describe('Spine', () => {
  it('mounts a small window for 10,000 runs and keeps the active option present', () => {
    render(<Spine runs={runs} onSelect={vi.fn()} selectedId="run-9999" />);
    expect(screen.getAllByRole('option').length).toBeLessThan(50);
    expect(screen.getByRole('option', { name: 'Run 10000, FAIL' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(
      document.getElementById(
        screen.getByRole('listbox').getAttribute('aria-activedescendant') ?? '',
      ),
    ).not.toBeNull();
  });
  it('moves selection with arrows, Home and End', () => {
    const select = vi.fn();
    render(<Spine runs={runs} onSelect={select} />);
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    expect(select).toHaveBeenLastCalledWith('run-1');
    fireEvent.keyDown(list, { key: 'End' });
    expect(select).toHaveBeenLastCalledWith('run-9999');
    fireEvent.keyDown(list, { key: 'Home' });
    expect(select).toHaveBeenLastCalledWith('run-0');
    fireEvent.keyDown(list, { key: 'ArrowUp' });
    expect(select).toHaveBeenLastCalledWith('run-0');
  });
  it('selects a clicked run', () => {
    const select = vi.fn();
    render(<Spine runs={runs.slice(0, 3)} onSelect={select} />);
    fireEvent.click(screen.getByRole('option', { name: 'Run 2, FAIL' }));
    expect(select).toHaveBeenCalledWith('run-1');
  });
  it('explains how to create an empty spine', () => {
    render(<Spine runs={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/Start a campaign/)).toBeInTheDocument();
  });
});
