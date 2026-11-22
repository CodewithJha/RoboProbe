import { lazy, Suspense, useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import type { PlotParams } from 'react-plotly.js';
import type { Schema } from '../../api/client';
import { useTheme } from '../../app/contexts';
import tokens from '../../styles/tokens.json';
import { loadPlotly } from '../charts/plotly';
import { heatmapAxis } from './hatchOverlay';
import styles from './RiskHeatmap.module.css';

const Plot = lazy(loadPlotly);
const WIDTH = 600;
const HEIGHT = 360;
const HALF_PROBABILITY = 0.5;
const UNCERTAIN_REGION = 1;
const DARK_QUERY = '(prefers-color-scheme: dark)';
const CONFIG = { displayModeBar: false, displaylogo: false } as const;
const CHART_STYLE = { display: 'block', position: 'absolute' } as const;

function colorSchemeQuery() {
  return typeof window.matchMedia === 'function' ? window.matchMedia(DARK_QUERY) : undefined;
}

function subscribeToColorScheme(update: () => void) {
  const query = colorSchemeQuery();
  query?.addEventListener('change', update);
  return () => {
    query?.removeEventListener('change', update);
  };
}

function prefersDark() {
  return colorSchemeQuery()?.matches ?? false;
}

function usePlotBounds() {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ width: number; height: number }>();
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      const { width, height } = element.getBoundingClientRect();
      if (width > 0 && height > 0) {
        setSize((previous) =>
          previous?.width === width && previous.height === height ? previous : { width, height },
        );
      }
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  return { ref, size };
}

type Cell = number | null | undefined;
interface Coordinates {
  x: number;
  y: number;
}
type Points = NonNullable<Schema['RiskSliceOut']['points']>;

function matchingPoints(points: Points, verdict: string, logX: boolean, logY: boolean) {
  return points.flatMap((point) => {
    const x = point['x'];
    const y = point['y'];
    return point['verdict'] === verdict &&
      typeof x === 'number' &&
      typeof y === 'number' &&
      (!logX || x > 0) &&
      (!logY || y > 0)
      ? [{ x, y }]
      : [];
  });
}

export function RiskPlot({
  xs,
  ys,
  probabilities,
  regions,
  logX,
  logY,
  points,
  thumb,
  onCellClick,
}: {
  xs: number[];
  ys: number[];
  probabilities: Cell[][];
  regions: unknown[][];
  logX: boolean;
  logY: boolean;
  points: Points;
  thumb: boolean;
  onCellClick: ((values: Coordinates) => void) | undefined;
}) {
  const { preference } = useTheme();
  const systemDark = useSyncExternalStore(subscribeToColorScheme, prefersDark, () => false);
  const colors =
    preference === 'dark' || (preference === 'system' && systemDark) ? tokens.dark : tokens.light;
  const { ref, size } = usePlotBounds();
  const hatch = useId();
  const x = heatmapAxis(xs, logX);
  const y = heatmapAxis(ys, logY);
  const z = probabilities.map((row) => row.map((value) => value ?? null));
  const data: PlotParams['data'] = [
    {
      type: 'heatmap',
      x: xs.length > 1 ? xs : x.edges,
      y: ys.length > 1 ? ys : y.edges,
      z,
      colorscale: [
        [0, colors['--risk-safe']],
        [HALF_PROBABILITY, colors['--risk-uncertain']],
        [1, colors['--risk-failure']],
      ],
      showlegend: false,
      showscale: false,
      zmin: 0,
      zmax: 1,
      hovertemplate: '%{x}, %{y}: %{z:.1%} failure probability<extra></extra>',
    },
    {
      type: 'contour',
      x: xs,
      y: ys,
      z,
      autocontour: false,
      contours: {
        start: HALF_PROBABILITY,
        end: HALF_PROBABILITY,
        size: HALF_PROBABILITY,
        coloring: 'none',
      },
      line: { color: colors['--ink'], width: 1 },
      showlegend: false,
      showscale: false,
      hoverinfo: 'skip',
    },
  ];
  if (!thumb) {
    for (const [verdict, symbol] of [
      ['PASS', 'circle-open'],
      ['FAIL', 'x'],
    ] as const) {
      const visible = matchingPoints(points, verdict, x.type === 'log', y.type === 'log');
      if (!visible.length) continue;
      data.push({
        type: 'scatter',
        mode: 'markers',
        x: visible.map((point) => point.x),
        y: visible.map((point) => point.y),
        marker: { symbol, color: colors['--ink'] },
        showlegend: false,
        hoverinfo: 'skip',
      });
    }
  }

  const handleCellClick = (event: { points: { curveNumber: number; pointNumber: unknown }[] }) => {
    const point = event.points.find(({ curveNumber }) => curveNumber === 0);
    // Plotly reports a [row, column] pair for heatmaps, unlike regular scatter points.
    const indices: unknown = point?.pointNumber;
    if (!Array.isArray(indices)) return;
    const row: unknown = indices[0];
    const column: unknown = indices[1];
    if (typeof row !== 'number' || typeof column !== 'number') return;
    const cellX = xs[column];
    const cellY = ys[row];
    if (cellX !== undefined && cellY !== undefined && probabilities[row]?.[column] != null) {
      onCellClick?.({ x: cellX, y: cellY });
    }
  };

  return (
    <div className={styles['plot']} aria-hidden="true" ref={ref}>
      <Suspense fallback={null}>
        <Plot
          className={styles['chart'] ?? ''}
          style={CHART_STYLE}
          data={data}
          layout={{
            ...size,
            autosize: !size,
            dragmode: false,
            margin: { l: 0, r: 0, b: 0, t: 0, pad: 0, autoexpand: false },
            plot_bgcolor: 'transparent',
            paper_bgcolor: 'transparent',
            xaxis: { type: x.type, range: x.range, fixedrange: true, visible: false },
            yaxis: { type: y.type, range: y.range, fixedrange: true, visible: false },
          }}
          config={{ ...CONFIG, staticPlot: thumb }}
          {...(onCellClick && !thumb ? { onClick: handleCellClick } : {})}
        />
      </Suspense>
      <svg
        className={styles['hatches']}
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        preserveAspectRatio="none"
      >
        <defs>
          <pattern id={hatch} width="8" height="8" patternUnits="userSpaceOnUse">
            <path d="M0 8L8 0" stroke="currentColor" opacity=".35" />
          </pattern>
        </defs>
        {regions.flatMap((row, rowIndex) =>
          row.map((region, column) => {
            if (region !== UNCERTAIN_REGION || probabilities[rowIndex]?.[column] == null)
              return null;
            const left = x.fractions[column] ?? 0;
            const right = x.fractions[column + 1] ?? 1;
            const bottom = y.fractions[rowIndex] ?? 0;
            const top = y.fractions[rowIndex + 1] ?? 1;
            return (
              <rect
                key={`${String(rowIndex)}:${String(column)}`}
                x={left * WIDTH}
                y={(1 - top) * HEIGHT}
                width={(right - left) * WIDTH}
                height={(top - bottom) * HEIGHT}
                fill={`url(#${hatch})`}
                pointerEvents="none"
              />
            );
          }),
        )}
      </svg>
    </div>
  );
}
