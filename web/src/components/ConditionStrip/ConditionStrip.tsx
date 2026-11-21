import * as Tooltip from '@radix-ui/react-tooltip';
import { componentConfig } from '../config';
import styles from './ConditionStrip.module.css';

export interface ConditionStripProps {
  readonly values: readonly number[];
  readonly labels: readonly string[];
  readonly highlight?: readonly number[];
  readonly size: 'xs' | 'sm' | 'md';
  readonly formatted?: readonly string[];
}
const BAR_WIDTH = 6;
const BAR_GAP = 3;
const HEIGHT = 24;
function normalized(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

/** Scenario glyph; focus exposes the same physical-value tooltip as pointer hover. */
export function ConditionStrip({
  values,
  labels,
  highlight = [],
  size,
  formatted,
}: ConditionStripProps) {
  const highlighted = new Set(highlight);
  const description =
    values
      .map((value, index) => {
        const name = labels[index] ?? `Parameter ${String(index + 1)}`;
        const physical =
          formatted?.[index] ?? `${String(Math.round(normalized(value) * 100))}% of range`;
        return `${name}: ${Number.isFinite(value) ? physical : 'unavailable'}${highlighted.has(index) ? ' (characteristic)' : ''}`;
      })
      .join('; ') || 'No enabled parameters';
  const width = Math.max(BAR_WIDTH, values.length * (BAR_WIDTH + BAR_GAP) - BAR_GAP);
  return (
    <Tooltip.Provider delayDuration={componentConfig.tooltipDelayMs}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            className={`${styles.trigger} ${styles[size]}`}
            aria-label={description}
          >
            <svg
              role="img"
              aria-label={description}
              viewBox={`0 0 ${String(width)} ${String(HEIGHT)}`}
            >
              {values.map((value, index) => (
                <g key={index} className={highlighted.has(index) ? styles.highlight : styles.bar}>
                  <rect
                    x={index * (BAR_WIDTH + BAR_GAP)}
                    y={0}
                    width={BAR_WIDTH}
                    height={HEIGHT}
                    className={styles.track}
                  />
                  <rect
                    x={index * (BAR_WIDTH + BAR_GAP)}
                    y={HEIGHT * (1 - normalized(value))}
                    width={BAR_WIDTH}
                    height={HEIGHT * normalized(value)}
                  />
                </g>
              ))}
            </svg>
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className={styles.tooltip}>{description}</Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
