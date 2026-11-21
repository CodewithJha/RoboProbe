import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatTable, type StatColumn } from './StatTable';

interface Row {
  id: string;
  speed: number;
}
const columns: StatColumn<Row>[] = [
  { key: 'id', header: 'Run', sortable: true },
  { key: 'speed', header: 'Speed', unit: 'm/s', align: 'right', sortable: true },
];
const rowKey = (row: Row) => row.id;
describe('StatTable', () => {
  it('sorts numerically, toggles aria-sort, and leaves input order intact', () => {
    const rows = [
      { id: 'a', speed: 10 },
      { id: 'b', speed: 2 },
      { id: 'c', speed: 2 },
    ];
    render(<StatTable rows={rows} columns={columns} rowKey={rowKey} caption="Runs" />);
    const speed = screen.getByRole('button', { name: /Speed/ });
    fireEvent.click(speed);
    expect(screen.getByRole('columnheader', { name: /Speed/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    const first = screen.getAllByRole('row')[1];
    expect(first).toBeDefined();
    if (first === undefined) throw new Error('Expected a first data row');
    expect(within(first).getByText('b')).toBeInTheDocument();
    fireEvent.click(speed);
    expect(screen.getByRole('columnheader', { name: /Speed/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(rows[0]?.id).toBe('a');
  });
  it('mounts only a viewport window for 10,000 rows', () => {
    const rows = Array.from({ length: 10000 }, (_, index) => ({ id: String(index), speed: index }));
    render(<StatTable rows={rows} columns={columns} rowKey={rowKey} caption="Large run table" />);
    expect(screen.getAllByRole('row').length).toBeLessThan(50);
    expect(screen.getAllByRole('row').length).toBeGreaterThan(2);
    expect(screen.getByRole('table')).toHaveAttribute('aria-rowcount', '10001');
  });
  it('shows a useful empty message', () => {
    render(
      <StatTable
        rows={[]}
        columns={columns}
        rowKey={rowKey}
        caption="Runs"
        emptyText="No completed runs yet."
      />,
    );
    expect(screen.getByText('No completed runs yet.')).toBeInTheDocument();
  });
});
