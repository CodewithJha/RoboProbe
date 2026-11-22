import { useId, useState } from 'react';
import type { Schema } from '../../api/client';
import styles from './RiskHeatmap.module.css';

interface Coordinates {
  x: number;
  y: number;
}
interface Props {
  slice: Schema['RiskSliceOut'];
  logX?: boolean;
  logY?: boolean;
  onCellClick?: (values: Coordinates) => void;
  size?: 'thumb' | 'full';
}

const WIDTH = 600;
const HEIGHT = 360;
const HALF_PROBABILITY = 0.5;
const THUMBNAIL_GRID = 16;

function thumbnailIndices(count: number) {
  const size = Math.min(count, THUMBNAIL_GRID);
  return Array.from({ length: size }, (_, i) =>
    Math.round((i * (count - 1)) / Math.max(1, size - 1)),
  );
}

function axis(values: number[], logarithmic: boolean, pixels: number) {
  const log = logarithmic && values.every((value) => value > 0);
  const transform = (value: number) => (log ? Math.log(value) : value);
  const coordinates = values.map(transform);
  const low = coordinates[0] ?? 0;
  const high = coordinates.at(-1) ?? low;
  const firstStep = (coordinates[1] ?? low + 1) - low;
  const lastStep = high - (coordinates.at(-2) ?? high - 1);
  const start = low - firstStep / 2;
  const end = high + lastStep / 2;
  const toPixels = (value: number) => ((value - start) / (end - start || 1)) * pixels;
  const bounds = coordinates.map((value, index) =>
    index === 0 ? 0 : toPixels((value + (coordinates[index - 1] ?? value)) / 2),
  );
  bounds.push(pixels);
  return { bounds, position: (value: number) => toPixels(transform(value)) };
}

function color(probability: number): string {
  const value = Math.max(0, Math.min(1, probability));
  const lower = value < HALF_PROBABILITY;
  const percent = (lower ? value : value - HALF_PROBABILITY) * 200;
  return `color-mix(in srgb, var(--risk-${lower ? 'safe' : 'uncertain'}) ${String(100 - percent)}%, var(--risk-${lower ? 'uncertain' : 'failure'}))`;
}

export function RiskHeatmap({
  slice,
  logX = slice.log_x,
  logY = slice.log_y,
  onCellClick,
  size = 'full',
}: Props) {
  const hatch = useId();
  const [tableOpen, setTableOpen] = useState(false);
  const fullX = slice.x_values ?? [];
  const fullY = slice.y_values ?? [];
  const xIndices = size === 'thumb' ? thumbnailIndices(fullX.length) : fullX.map((_, i) => i);
  const yIndices = size === 'thumb' ? thumbnailIndices(fullY.length) : fullY.map((_, i) => i);
  const xs = xIndices.map((i) => fullX[i] ?? 0);
  const ys = yIndices.map((i) => fullY[i] ?? 0);
  const probabilities = yIndices.map((row) =>
    xIndices.map((column) => slice.p_fail?.[row]?.[column]),
  );
  const regions = yIndices.map((row) => xIndices.map((column) => slice.region?.[row]?.[column]));
  const [xAxis, yAxis] = [axis(xs, logX, WIDTH), axis(ys, logY, HEIGHT)];
  const label = `${slice.x_param} by ${slice.y_param} failure probability`;
  if (!xs.length || !ys.length || !slice.p_fail?.length) return <p>No risk grid is available.</p>;

  return (
    <figure className={styles['figure']} aria-label={label}>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        className={styles['plot']}
        aria-hidden="true"
      >
        <defs>
          <pattern id={hatch} width="8" height="8" patternUnits="userSpaceOnUse">
            <path d="M0 8L8 0" stroke="currentColor" opacity=".35" />
          </pattern>
        </defs>
        {ys.map((y, row) =>
          xs.map((x, column) => {
            const probability = probabilities[row]?.[column];
            if (probability === undefined) return null;
            const left = xAxis.bounds[column] ?? 0;
            const right = xAxis.bounds[column + 1] ?? WIDTH;
            const bottom = HEIGHT - (yAxis.bounds[row] ?? 0);
            const top = HEIGHT - (yAxis.bounds[row + 1] ?? HEIGHT);
            const uncertain = regions[row]?.[column] === 1;
            const above = probabilities[row + 1]?.[column];
            const next = probabilities[row]?.[column + 1];
            const crosses = (neighbor?: number) =>
              neighbor !== undefined &&
              neighbor < HALF_PROBABILITY !== probability < HALF_PROBABILITY;
            return (
              <g key={`${String(column)}:${String(row)}`}>
                {/* The equivalent focusable control is in the data table. */}
                <rect
                  x={left}
                  y={top}
                  width={right - left}
                  height={bottom - top}
                  fill={color(probability)}
                  onClick={
                    size === 'full' && onCellClick
                      ? () => {
                          onCellClick({ x, y });
                        }
                      : undefined
                  }
                >
                  {size === 'full' ? (
                    <title>{`${String(x)}, ${String(y)}: ${(probability * 100).toFixed(1)}% probability of failure`}</title>
                  ) : null}
                </rect>
                {uncertain && (
                  <rect
                    x={left}
                    y={top}
                    width={right - left}
                    height={bottom - top}
                    fill={`url(#${hatch})`}
                    pointerEvents="none"
                  />
                )}
                {crosses(next) && (
                  <path
                    d={`M${String(right)} ${String(top)}V${String(bottom)}`}
                    stroke="currentColor"
                    pointerEvents="none"
                  />
                )}
                {crosses(above) && (
                  <path
                    d={`M${String(left)} ${String(top)}H${String(right)}`}
                    stroke="currentColor"
                    pointerEvents="none"
                  />
                )}
              </g>
            );
          }),
        )}
        {size === 'full' &&
          slice.points?.map((point, index) => {
            const x = point['x'];
            const y = point['y'];
            const verdict = point['verdict'];
            if (
              typeof x !== 'number' ||
              typeof y !== 'number' ||
              (verdict !== 'PASS' && verdict !== 'FAIL') ||
              (logX && x <= 0) ||
              (logY && y <= 0)
            )
              return null;
            const cx = xAxis.position(x);
            const cy = HEIGHT - yAxis.position(y);
            return verdict === 'PASS' ? (
              <circle
                key={index}
                cx={cx}
                cy={cy}
                r="5"
                fill="none"
                stroke="currentColor"
                pointerEvents="none"
              />
            ) : (
              <path
                key={index}
                d={`M${String(cx - 5)} ${String(cy - 5)}l10 10m-10 0l10 -10`}
                stroke="currentColor"
                pointerEvents="none"
              />
            );
          })}
      </svg>
      {size === 'full' && (
        <>
          <figcaption>
            {slice.x_param}: {xs[0]}–{xs.at(-1)}
            {logX ? ' (log)' : ''} · {slice.y_param}: {ys[0]}–{ys.at(-1)}
            {logY ? ' (log)' : ''}. ○ Pass · × Fail · hatched uncertain · line at 50%.
          </figcaption>
          <details
            onToggle={(event) => {
              setTableOpen(event.currentTarget.open);
            }}
          >
            <summary>Risk data table</summary>
            {tableOpen && (
              <div className={styles['table']}>
                <table>
                  <caption>{label}</caption>
                  <thead>
                    <tr>
                      <th scope="col">
                        {slice.y_param} / {slice.x_param}
                      </th>
                      {xs.map((x, column) => (
                        <th scope="col" key={column}>
                          {x}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ys.map((y, row) => (
                      <tr key={row}>
                        <th scope="row">{y}</th>
                        {xs.map((x, column) => {
                          const probability = probabilities[row]?.[column];
                          const percentage =
                            probability === undefined
                              ? 'Unavailable'
                              : `${(probability * 100).toFixed(1)}%`;
                          return (
                            <td key={column}>
                              {onCellClick && probability !== undefined ? (
                                <button
                                  type="button"
                                  onClick={() => {
                                    onCellClick({ x, y });
                                  }}
                                  aria-label={`${percentage} failure probability. Probe ${slice.x_param} ${String(x)}, ${slice.y_param} ${String(y)}`}
                                >
                                  {percentage}
                                </button>
                              ) : (
                                percentage
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>
        </>
      )}
    </figure>
  );
}
