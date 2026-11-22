import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import {
  nearestTime,
  screenToWorld,
  worldToScreen,
  type MapGeometry,
  type Point,
  type Viewport,
} from './transform';
import { plotDefaults } from './plotDefaults';
import styles from './TrajectoryPlot.module.css';

export interface TraceColumns {
  readonly t: readonly number[];
  readonly gt_x: readonly number[];
  readonly gt_y: readonly number[];
  readonly gt_yaw: readonly number[];
  readonly est_x: readonly number[];
  readonly est_y: readonly number[];
}
export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly yaw?: number;
}
export interface TrajectoryPlotProps {
  readonly trace: TraceColumns;
  readonly map?: MapGeometry;
  readonly obstacles?: readonly Rect[];
  readonly footprint?: readonly Point[];
  readonly firstViolationT?: number;
  readonly cursorT?: number;
  readonly onCursorChange?: (t: number) => void;
  readonly ghostIntervalS?: number;
}
const INITIAL: Viewport = { zoom: 1, pan: [0, 0] };
function traceMap(trace: TraceColumns): MapGeometry {
  if (!trace.gt_x.length) return { origin: [0, 0], resolution: 1, width: 720, height: 420 };
  const minX = Math.min(...trace.gt_x.filter(Number.isFinite)),
    maxX = Math.max(...trace.gt_x.filter(Number.isFinite));
  const minY = Math.min(...trace.gt_y.filter(Number.isFinite)),
    maxY = Math.max(...trace.gt_y.filter(Number.isFinite));
  const span = Math.max(maxX - minX, maxY - minY, plotDefaults.minimumWorldSpan);
  return {
    origin: [minX - span / 10, minY - span / 10],
    resolution: (span * 1.2) / plotDefaults.height,
    width: plotDefaults.width,
    height: plotDefaults.height,
  };
}
function points(trace: TraceColumns, map: MapGeometry, estimated = false): string {
  const xs = estimated ? trace.est_x : trace.gt_x;
  const ys = estimated ? trace.est_y : trace.gt_y;
  return xs.map((x, index) => worldToScreen([x, ys[index] ?? 0], map, INITIAL).join(',')).join(' ');
}
function robotPolygon(
  trace: TraceColumns,
  index: number,
  footprint: readonly Point[],
  map: MapGeometry,
): string {
  const x = trace.gt_x[index] ?? 0,
    y = trace.gt_y[index] ?? 0,
    yaw = trace.gt_yaw[index] ?? 0;
  return footprint
    .map(([dx, dy]) =>
      worldToScreen(
        [x + dx * Math.cos(yaw) - dy * Math.sin(yaw), y + dx * Math.sin(yaw) + dy * Math.cos(yaw)],
        map,
        INITIAL,
      ).join(','),
    )
    .join(' ');
}

/** Inspectable world-coordinate trajectory; absent geometry remains explicitly unavailable. */
export function TrajectoryPlot({
  trace,
  map: suppliedMap,
  obstacles = [],
  footprint = [],
  firstViolationT,
  cursorT,
  onCursorChange,
  ghostIntervalS = plotDefaults.ghostIntervalS,
}: TrajectoryPlotProps) {
  const [viewport, setViewport] = useState<Viewport>(INITIAL);
  const svg = useRef<SVGSVGElement>(null);
  const pointers = useRef(new Map<number, Point>());
  const pinch = useRef<{ distance: number; zoom: number } | null>(null);
  useEffect(() => {
    const element = svg.current;
    function wheel(event: globalThis.WheelEvent) {
      event.preventDefault();
      setViewport((current) => ({
        ...current,
        zoom: Math.min(
          plotDefaults.maxZoom,
          Math.max(
            plotDefaults.minZoom,
            current.zoom * (event.deltaY < 0 ? plotDefaults.zoomStep : 1 / plotDefaults.zoomStep),
          ),
        ),
      }));
    }
    element?.addEventListener('wheel', wheel, { passive: false });
    return () => {
      element?.removeEventListener('wheel', wheel);
    };
  }, []);
  const drag = useRef<{ x: number; y: number; pan: Point } | null>(null);
  const map = useMemo(() => suppliedMap ?? traceMap(trace), [suppliedMap, trace]);
  const groundTruth = useMemo(() => points(trace, map), [trace, map]);
  const estimated = useMemo(() => points(trace, map, true), [trace, map]);
  const interval =
    Number.isFinite(ghostIntervalS) && ghostIntervalS > 0
      ? ghostIntervalS
      : plotDefaults.ghostIntervalS;
  const ghosts = useMemo(() => {
    const indices: number[] = [];
    const end = trace.t[trace.t.length - 1];
    if (end === undefined) return indices;
    for (let t = trace.t[0] ?? 0; t <= end; t += interval) {
      const index = nearestTime(trace.t, t);
      if (indices[indices.length - 1] !== index) indices.push(index);
    }
    return indices;
  }, [trace.t, interval]);
  const cursorIndex = nearestTime(trace.t, cursorT ?? trace.t[0] ?? 0);
  const violationIndex = firstViolationT === undefined ? -1 : nearestTime(trace.t, firstViolationT);
  const cursorPoint = worldToScreen(
    [trace.gt_x[cursorIndex] ?? 0, trace.gt_y[cursorIndex] ?? 0],
    map,
    INITIAL,
  );
  const failurePoint = worldToScreen(
    [trace.gt_x[violationIndex] ?? 0, trace.gt_y[violationIndex] ?? 0],
    map,
    INITIAL,
  );
  function zoom(multiplier: number) {
    setViewport((current) => ({
      ...current,
      zoom: Math.min(
        plotDefaults.maxZoom,
        Math.max(plotDefaults.minZoom, current.zoom * multiplier),
      ),
    }));
  }
  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    const movements: Record<string, Point> = {
      ArrowLeft: [plotDefaults.panStep, 0],
      ArrowRight: [-plotDefaults.panStep, 0],
      ArrowUp: [0, plotDefaults.panStep],
      ArrowDown: [0, -plotDefaults.panStep],
    };
    const movement = movements[event.key];
    if (movement !== undefined) {
      event.preventDefault();
      setViewport((current) => ({
        ...current,
        pan: [current.pan[0] + movement[0], current.pan[1] + movement[1]],
      }));
    } else if (event.key === '+' || event.key === '=') {
      event.preventDefault();
      zoom(plotDefaults.zoomStep);
    } else if (event.key === '-') {
      event.preventDefault();
      zoom(1 / plotDefaults.zoomStep);
    } else if (event.key === '0') {
      event.preventDefault();
      setViewport(INITIAL);
    }
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    if (pointers.current.has(event.pointerId))
      pointers.current.set(event.pointerId, [event.clientX, event.clientY]);
    const active = [...pointers.current.values()];
    if (active.length === 2 && pinch.current && active[0] && active[1]) {
      const distance = Math.hypot(active[0][0] - active[1][0], active[0][1] - active[1][1]);
      const start = pinch.current;
      setViewport((current) => ({
        ...current,
        zoom: Math.min(
          plotDefaults.maxZoom,
          Math.max(plotDefaults.minZoom, (start.zoom * distance) / start.distance),
        ),
      }));
      return;
    }
    if (drag.current !== null) {
      const start = drag.current;
      setViewport((current) => ({
        ...current,
        pan: [start.pan[0] + event.clientX - start.x, start.pan[1] + event.clientY - start.y],
      }));
      return;
    }
    if (onCursorChange === undefined) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const world = screenToWorld(
      [
        ((event.clientX - bounds.left) * map.width) / bounds.width,
        ((event.clientY - bounds.top) * map.height) / bounds.height,
      ],
      map,
      viewport,
    );
    let closest = -1,
      distance = Number.POSITIVE_INFINITY;
    trace.t.forEach((_, index) => {
      const d =
        ((trace.gt_x[index] ?? 0) - world[0]) ** 2 + ((trace.gt_y[index] ?? 0) - world[1]) ** 2;
      if (d < distance) {
        distance = d;
        closest = index;
      }
    });
    const t = trace.t[closest];
    if (t !== undefined) onCursorChange(t);
  }
  if (trace.t.length === 0) return <p>Trajectory is unavailable for this run.</p>;
  return (
    <section className={styles['root']} aria-label="Robot trajectory">
      <div className={styles['toolbar']}>
        <span>Ground truth — · Estimated – –</span>
        <button
          type="button"
          onClick={() => {
            zoom(plotDefaults.zoomStep);
          }}
          aria-label="Zoom in trajectory"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => {
            zoom(1 / plotDefaults.zoomStep);
          }}
          aria-label="Zoom out trajectory"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => {
            setViewport(INITIAL);
          }}
        >
          Reset view
        </button>
      </div>
      {suppliedMap?.imageUrl === undefined && suppliedMap?.occupancyPath === undefined ? (
        <p className={styles['note']}>
          Occupancy map unavailable; showing the recorded trajectory in world coordinates.
        </p>
      ) : null}
      <svg
        ref={svg}
        role="application"
        tabIndex={0}
        aria-label="Interactive trajectory. Plus/minus zoom, arrows pan, zero resets."
        viewBox={`0 0 ${String(map.width)} ${String(map.height)}`}
        className={styles['plot']}
        onKeyDown={keyboard}
        onPointerDown={(event) => {
          pointers.current.set(event.pointerId, [event.clientX, event.clientY]);
          const active = [...pointers.current.values()];
          if (active.length === 2 && active[0] && active[1])
            pinch.current = {
              distance: Math.max(
                1,
                Math.hypot(active[0][0] - active[1][0], active[0][1] - active[1][1]),
              ),
              zoom: viewport.zoom,
            };
          drag.current = { x: event.clientX, y: event.clientY, pan: viewport.pan };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={move}
        onPointerUp={(event) => {
          pointers.current.delete(event.pointerId);
          pinch.current = null;
          drag.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          pointers.current.clear();
          pinch.current = null;
          drag.current = null;
        }}
      >
        <g
          data-testid="trajectory-viewport"
          transform={`translate(${String(viewport.pan[0])} ${String(viewport.pan[1])}) scale(${String(viewport.zoom)})`}
        >
          {map.imageUrl === undefined ? null : (
            <image href={map.imageUrl} width={map.width} height={map.height} />
          )}
          {map.occupancyPath ? (
            <path d={map.occupancyPath} className={styles['occupancy']} />
          ) : null}
          <polyline points={groundTruth} className={styles['ground-truth']} />
          <polyline points={estimated} className={styles['estimated']} />
          {obstacles.map((obstacle, index) => {
            const p = worldToScreen([obstacle.x, obstacle.y], map, INITIAL);
            return (
              <rect
                key={index}
                x={p[0] - obstacle.width / map.resolution / 2}
                y={p[1] - obstacle.height / map.resolution / 2}
                transform={`rotate(${String((-(obstacle.yaw ?? 0) * 180) / Math.PI)} ${String(p[0])} ${String(p[1])})`}
                width={obstacle.width / map.resolution}
                height={obstacle.height / map.resolution}
                className={styles['obstacle']}
              />
            );
          })}
          {footprint.length === 0
            ? null
            : ghosts.map((index) => (
                <polygon
                  key={index}
                  points={robotPolygon(trace, index, footprint, map)}
                  className={styles['ghost']}
                />
              ))}
          {violationIndex < 0 ? null : (
            <path
              data-testid="first-violation"
              className={styles['failure']}
              d={`M${String(failurePoint[0] - plotDefaults.pointRadius)} ${String(failurePoint[1] - plotDefaults.pointRadius)}l${String(plotDefaults.pointRadius * 2)} ${String(plotDefaults.pointRadius * 2)}m0 -${String(plotDefaults.pointRadius * 2)}l-${String(plotDefaults.pointRadius * 2)} ${String(plotDefaults.pointRadius * 2)}`}
            />
          )}
          <circle
            data-testid="trajectory-cursor"
            data-time={cursorT ?? trace.t[0]}
            cx={cursorPoint[0]}
            cy={cursorPoint[1]}
            r={plotDefaults.pointRadius}
            className={styles['cursor']}
          />
          {footprint.length === 0 ? null : (
            <polygon
              points={robotPolygon(trace, cursorIndex, footprint, map)}
              className={styles['robot']}
            />
          )}
        </g>
      </svg>
    </section>
  );
}
