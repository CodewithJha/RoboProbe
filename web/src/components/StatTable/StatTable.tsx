import { useVirtualizer } from '@tanstack/react-virtual';
import { useMemo, useRef, useState, type ReactNode } from 'react';
import { componentConfig } from '../config';
import { initialVirtualWindow } from '../virtualWindow';
import styles from './StatTable.module.css';

export interface StatColumn<T> {
  readonly key: keyof T;
  readonly header: string;
  readonly align?: 'left' | 'right';
  readonly unit?: string;
  readonly format?: (value: T[keyof T], row: T) => ReactNode;
  readonly sortable?: boolean;
}
export interface StatTableProps<T extends object> {
  readonly rows: readonly T[];
  readonly columns: readonly StatColumn<T>[];
  readonly rowKey: (row: T) => string;
  readonly caption: string;
  readonly emptyText?: string;
  readonly height?: number;
}
function display(value: unknown): string {
  if (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  )
    return String(value);
  if (value instanceof Date) return value.toISOString();
  return '—';
}
function compare(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return typeof a === 'number' && typeof b === 'number'
    ? a - b
    : display(a).localeCompare(display(b), undefined, { numeric: true });
}

/** Semantic, stable-sort statistics table; large datasets mount only a viewport window. */
export function StatTable<T extends object>({
  rows,
  columns,
  rowKey,
  caption,
  emptyText = 'No data available.',
  height = componentConfig.rowHeight * componentConfig.viewportRows,
}: StatTableProps<T>) {
  const parent = useRef<HTMLDivElement>(null);
  const [sort, setSort] = useState<{ key: keyof T; descending: boolean } | null>(null);
  const sorted = useMemo(
    () =>
      sort === null
        ? rows
        : rows
            .map((row, index) => ({ row, index }))
            .sort((a, b) => {
              const order = compare(a.row[sort.key], b.row[sort.key]);
              return (sort.descending ? -order : order) || a.index - b.index;
            })
            .map(({ row }) => row),
    [rows, sort],
  );
  const virtualized = rows.length > componentConfig.tableVirtualizationThreshold;
  // eslint-disable-next-line react-hooks/incompatible-library -- Keep the TanStack instance local and outside memoized children.
  const virtualizer = useVirtualizer({
    count: virtualized ? sorted.length : 0,
    getScrollElement: () => parent.current,
    estimateSize: () => componentConfig.rowHeight,
    getItemKey: (index) => (sorted[index] === undefined ? index : rowKey(sorted[index])),
    initialRect: { width: 800, height },
    overscan: componentConfig.overscan,
  });
  const measured = virtualizer.getVirtualItems();
  const items =
    measured.length === 0
      ? initialVirtualWindow(sorted.length, height, componentConfig.rowHeight)
      : measured;
  const indices = virtualized ? items.map((item) => item.index) : sorted.map((_, index) => index);
  const first = items[0];
  const last = items[items.length - 1];
  return (
    <div
      ref={parent}
      className={styles.viewport}
      style={virtualized ? { height } : undefined}
      role="region"
      aria-label={`${caption} table`}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focusable overflow lets keyboard users scroll the semantic table.
      tabIndex={virtualized ? 0 : undefined}
    >
      <table className={styles.table} aria-rowcount={sorted.length + 1}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={String(column.key)}
                scope="col"
                className={column.align === 'right' ? styles.numeric : undefined}
                aria-sort={
                  sort?.key === column.key
                    ? sort.descending
                      ? 'descending'
                      : 'ascending'
                    : undefined
                }
              >
                {column.sortable === true ? (
                  <button
                    type="button"
                    className={styles.sort}
                    onClick={() => {
                      setSort({
                        key: column.key,
                        descending: sort?.key === column.key ? !sort.descending : false,
                      });
                      if (parent.current !== null) parent.current.scrollTop = 0;
                    }}
                  >
                    {column.header}
                    {column.unit === undefined ? '' : ` (${column.unit})`}
                    <span aria-hidden="true">
                      {sort?.key === column.key ? (sort.descending ? ' ↓' : ' ↑') : ' ↕'}
                    </span>
                  </button>
                ) : (
                  <>
                    {column.header}
                    {column.unit === undefined ? '' : ` (${column.unit})`}
                  </>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {virtualized && first !== undefined && first.start > 0 ? (
            <tr aria-hidden="true">
              <td
                colSpan={columns.length}
                className={styles.spacer}
                style={{ height: first.start }}
              />
            </tr>
          ) : null}
          {indices.map((index) => {
            const row = sorted[index];
            if (row === undefined) return null;
            return (
              <tr
                key={rowKey(row)}
                aria-rowindex={index + 2}
                style={virtualized ? { height: componentConfig.rowHeight } : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={String(column.key)}
                    className={column.align === 'right' ? styles.numeric : undefined}
                  >
                    {column.format === undefined
                      ? display(row[column.key])
                      : column.format(row[column.key], row)}
                  </td>
                ))}
              </tr>
            );
          })}
          {virtualized && last !== undefined && virtualizer.getTotalSize() > last.end ? (
            <tr aria-hidden="true">
              <td
                colSpan={columns.length}
                className={styles.spacer}
                style={{ height: virtualizer.getTotalSize() - last.end }}
              />
            </tr>
          ) : null}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>{emptyText}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
