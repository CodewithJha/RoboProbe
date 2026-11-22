import { useState } from 'react';
import type { Schema } from '../../api/client';
import { RiskPlot } from './RiskPlot';
import styles from './RiskHeatmap.module.css';

interface Coordinates {
  x: number;
  y: number;
}
type RiskSliceView = Schema['RiskSliceOut'];
interface Props {
  slice: RiskSliceView;
  logX?: boolean;
  logY?: boolean;
  onCellClick?: (values: Coordinates) => void;
  size?: 'thumb' | 'full';
}

const THUMBNAIL_GRID = 16;

function thumbnailIndices(count: number) {
  const size = Math.min(count, THUMBNAIL_GRID);
  return Array.from({ length: size }, (_, i) =>
    Math.round((i * (count - 1)) / Math.max(1, size - 1)),
  );
}

export function RiskHeatmap({
  slice,
  logX = slice.log_x ?? false,
  logY = slice.log_y ?? false,
  onCellClick,
  size = 'full',
}: Props) {
  const [tableOpen, setTableOpen] = useState(false);
  const fullX = slice.x_values ?? [];
  const fullY = slice.y_values ?? [];
  const xIndices =
    size === 'thumb' ? thumbnailIndices(fullX.length) : fullX.map((_: number, i: number) => i);
  const yIndices =
    size === 'thumb' ? thumbnailIndices(fullY.length) : fullY.map((_: number, i: number) => i);
  const xs = xIndices.map((i) => fullX[i] ?? 0);
  const ys = yIndices.map((i) => fullY[i] ?? 0);
  const probabilities = yIndices.map((row) =>
    xIndices.map((column) => slice.p_fail?.[row]?.[column]),
  );
  const regions = yIndices.map((row) => xIndices.map((column) => slice.region?.[row]?.[column]));
  const label = `${slice.x_param} by ${slice.y_param} failure probability`;
  if (!xs.length || !ys.length || !slice.p_fail?.length) return <p>No risk grid is available.</p>;

  return (
    <figure className={styles['figure']} aria-label={label}>
      <RiskPlot
        xs={xs}
        ys={ys}
        probabilities={probabilities}
        regions={regions}
        logX={logX}
        logY={logY}
        points={slice.points ?? []}
        thumb={size === 'thumb'}
        onCellClick={onCellClick}
      />
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
                      {xs.map((x: number, column: number) => (
                        <th scope="col" key={column}>
                          {x}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ys.map((y: number, row: number) => (
                      <tr key={row}>
                        <th scope="row">{y}</th>
                        {xs.map((x, column) => {
                          const probability = probabilities[row]?.[column];
                          const percentage =
                            probability == null
                              ? 'Unavailable'
                              : `${(probability * 100).toFixed(1)}%`;
                          return (
                            <td key={column}>
                              {onCellClick && probability != null ? (
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
