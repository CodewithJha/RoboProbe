import { useEffect, useMemo, useRef, useState } from 'react';
import type { Schema } from '../../../api/client';
import { TimelineChart, type TimelineBand } from '../../../components/TimelineChart/TimelineChart';
import { TrajectoryPlot } from '../../../components/TrajectoryPlot/TrajectoryPlot';
import type { MapGeometry, Point } from '../../../components/TrajectoryPlot/transform';
import { object, number } from '../runData';

const navStates = ['IDLE', 'ACTIVE', 'SUCCEEDED', 'ABORTED', 'CANCELED'];
const navTones = ['neutral', 'uncertain', 'safe', 'failure', 'neutral'] as const;

export function RunCharts({
  trace,
  run,
  startMap,
}: {
  trace: Schema['TraceOut'];
  run: Schema['RunOut'];
  startMap?: MapGeometry;
}) {
  const [cursor, setCursor] = useState<number>();
  const frame = useRef<number | undefined>(undefined);
  const pending = useRef<number | undefined>(undefined);

  useEffect(
    () => () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    },
    [],
  );

  function onCursorChange(t: number) {
    pending.current = t;
    if (frame.current !== undefined) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = undefined;
      setCursor(pending.current);
    });
  }

  const data = useMemo(() => {
    const t = trace.t;
    const col = (key: string) => t.map((_, i) => number(trace.columns[key]?.[i]) ?? Number.NaN);
    const gt_x = col('gt_x'),
      gt_y = col('gt_y'),
      gt_yaw = col('gt_yaw');
    const est_x = col('est_x'),
      est_y = col('est_y');
    const trajectory = { t, gt_x, gt_y, gt_yaw, est_x, est_y };
    const positionsAvailable = gt_x.some(Number.isFinite) && gt_y.some(Number.isFinite);
    const nav = col('nav_status');
    const bands: TimelineBand[] = [];
    for (const [i, state] of nav.entries()) {
      const start = t[i],
        end = t[i + 1];
      const label = navStates[state],
        tone = navTones[state];
      if (start === undefined || end === undefined || label === undefined || tone === undefined)
        continue;
      const previous = bands[bands.length - 1];
      if (previous?.label === label && previous.end === start) {
        bands[bands.length - 1] = { ...previous, end };
      } else {
        bands.push({ start, end, label, tone });
      }
    }
    const localisation = gt_x.map((x, i) =>
      Math.hypot(x - (est_x[i] ?? Number.NaN), (gt_y[i] ?? Number.NaN) - (est_y[i] ?? Number.NaN)),
    );
    return {
      trajectory,
      positionsAvailable,
      bands,
      clearance: [{ t, y: col('min_obstacle_dist'), label: 'Minimum clearance' }],
      localisation: [{ t, y: localisation, label: 'Position error' }],
      speed: [
        { t, y: col('cmd_v'), label: 'Commanded speed' },
        { t, y: col('meas_v'), label: 'Measured speed', style: 'dashed' as const },
      ],
      navigation: [{ t, y: nav, label: 'Navigation state' }],
    };
  }, [trace]);

  const snapshot = object(object(run.manifest)['config_snapshot']);
  const oracles = object(snapshot['oracles']);
  const clearance = number(object(oracles['clear'])['d_safe']);
  const localisation = number(object(oracles['loc'])['e_max']);
  const firstViolationT = run.oracles
    ?.flatMap((row) => {
      const t = number(row['first_violation_t']);
      return row['violated'] === true && t !== undefined ? [t] : [];
    })
    .reduce<number | undefined>(
      (first, t) => (first === undefined ? t : Math.min(first, t)),
      undefined,
    );
  const manifestFootprint = (
    Array.isArray(snapshot['footprint']) ? snapshot['footprint'] : []
  ).flatMap((value): Point[] => {
    const x = Array.isArray(value) ? number(value[0]) : undefined;
    const y = Array.isArray(value) ? number(value[1]) : undefined;
    return x === undefined || y === undefined ? [] : [[x, y]];
  });
  const radius = startMap?.footprintRadius;
  const footprint =
    manifestFootprint.length > 0 || radius === undefined
      ? manifestFootprint
      : Array.from({ length: 16 }, (_, i): Point => {
          const angle = (i / 16) * Math.PI * 2;
          return [Math.cos(angle) * radius, Math.sin(angle) * radius];
        });
  const shared = { cursorT: cursor ?? trace.t[0] ?? 0, onCursorChange };

  return (
    <section aria-label="Run trace">
      <h2>Trace</h2>
      {trace.t.length === 0 ? (
        <p>The recorded trace has no samples.</p>
      ) : (
        <>
          {data.positionsAvailable ? (
            <TrajectoryPlot
              trace={data.trajectory}
              {...(startMap ? { map: startMap } : {})}
              footprint={footprint}
              obstacles={startMap?.obstacle ? [startMap.obstacle] : []}
              {...(firstViolationT === undefined ? {} : { firstViolationT })}
              {...shared}
            />
          ) : (
            <p>Trajectory positions are unavailable.</p>
          )}
          <TimelineChart
            title="Clearance"
            yUnit="m"
            series={data.clearance}
            thresholds={
              clearance === undefined ? [] : [{ value: clearance, label: 'Safe clearance' }]
            }
            {...shared}
          />
          <TimelineChart
            title="Localisation error"
            yUnit="m"
            series={data.localisation}
            thresholds={
              localisation === undefined ? [] : [{ value: localisation, label: 'Maximum error' }]
            }
            {...shared}
          />
          <TimelineChart title="Forward speed" yUnit="m/s" series={data.speed} {...shared} />
          <TimelineChart
            title="Navigation status"
            yUnit="state"
            series={data.navigation}
            bands={data.bands}
            {...shared}
          />
        </>
      )}
    </section>
  );
}
