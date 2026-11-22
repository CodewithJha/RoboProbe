import { defaultRangeExtractor, useVirtualizer } from '@tanstack/react-virtual';
import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { componentConfig } from '../config';
import { initialVirtualWindow } from '../virtualWindow';
import { VerdictNotch, type Verdict } from '../VerdictNotch/VerdictNotch';
import styles from './Spine.module.css';

export interface SpineRun {
  readonly id: string;
  readonly ordinal: number;
  readonly verdict: Verdict;
}
export interface SpineProps {
  readonly runs: readonly SpineRun[];
  readonly onSelect: (id: string) => void;
  readonly selectedId?: string;
  readonly label?: string;
  readonly height?: number;
}

/** Virtual run timeline with roving selection and a single keyboard entry point. */
export function Spine({
  runs,
  onSelect,
  selectedId,
  label = 'Campaign run spine',
  height = componentConfig.spineTickHeight * componentConfig.viewportRows,
}: SpineProps) {
  const parent = useRef<HTMLDivElement>(null);
  const prefix = useId();
  const [internalId, setInternalId] = useState<string | undefined>(runs[0]?.id);
  const indexById = useMemo(() => new Map(runs.map((run, index) => [run.id, index])), [runs]);
  const activeId = selectedId ?? internalId;
  const activeIndex = activeId === undefined ? 0 : (indexById.get(activeId) ?? 0);
  // eslint-disable-next-line react-hooks/incompatible-library -- Keep the TanStack instance local and outside memoized children.
  const virtualizer = useVirtualizer({
    count: runs.length,
    getScrollElement: () => parent.current,
    estimateSize: () => componentConfig.spineTickHeight,
    getItemKey: (index) => runs[index]?.id ?? index,
    initialRect: { width: 240, height },
    overscan: componentConfig.overscan,
    rangeExtractor: (range) =>
      [...new Set([...defaultRangeExtractor(range), activeIndex])]
        .filter((index) => index < runs.length)
        .sort((a, b) => a - b),
  });
  const measured = virtualizer.getVirtualItems();
  const visible =
    measured.length === 0
      ? initialVirtualWindow(runs.length, height, componentConfig.spineTickHeight)
      : measured;
  const items = visible.some((item) => item.index === activeIndex)
    ? visible
    : [
        ...visible,
        {
          index: activeIndex,
          key: activeIndex,
          start: activeIndex * componentConfig.spineTickHeight,
          size: componentConfig.spineTickHeight,
        },
      ];
  function choose(index: number) {
    const run = runs[index];
    if (run === undefined) return;
    setInternalId(run.id);
    virtualizer.scrollToIndex(index, { align: 'auto' });
    onSelect(run.id);
  }
  function navigate(event: KeyboardEvent<HTMLDivElement>) {
    const next =
      event.key === 'ArrowDown'
        ? Math.min(runs.length - 1, activeIndex + 1)
        : event.key === 'ArrowUp'
          ? Math.max(0, activeIndex - 1)
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? runs.length - 1
              : undefined;
    if (next === undefined) return;
    event.preventDefault();
    choose(next);
  }
  if (runs.length === 0)
    return <p className={styles.empty}>No runs yet. Start a campaign to build its spine.</p>;
  return (
    <div
      ref={parent}
      role="listbox"
      tabIndex={0}
      aria-label={label}
      aria-activedescendant={`${prefix}-${String(activeIndex)}`}
      onKeyDown={navigate}
      className={styles.viewport}
      style={{ height }}
    >
      <div className={styles.track} style={{ height: virtualizer.getTotalSize() }}>
        {items.map((item) => {
          const run = runs[item.index];
          if (run === undefined) return null;
          return (
            <div
              key={item.key}
              id={`${prefix}-${String(item.index)}`}
              role="option"
              tabIndex={-1}
              aria-selected={item.index === activeIndex}
              aria-posinset={item.index + 1}
              aria-setsize={runs.length}
              aria-label={`Run ${String(run.ordinal)}, ${run.verdict}`}
              onClick={() => {
                choose(item.index);
                parent.current?.focus();
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  choose(item.index);
                }
              }}
              className={styles.tick}
              style={{ height: item.size, transform: `translateY(${String(item.start)}px)` }}
            >
              <span className={styles.ordinal}>{run.ordinal}</span>
              <VerdictNotch verdict={run.verdict} />
              <span className={styles.rule} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
