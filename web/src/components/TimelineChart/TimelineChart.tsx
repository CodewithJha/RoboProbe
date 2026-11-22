import { useId, useMemo, useState, type PointerEvent } from 'react';
import { StatTable, type StatColumn } from '../StatTable/StatTable';
import { linearScale, niceTicks } from './scale';
import styles from './TimelineChart.module.css';

export interface TimelineSeries { readonly t: readonly number[]; readonly y: readonly number[]; readonly label: string; readonly style?: 'solid' | 'dashed'; }
export interface TimelineThreshold { readonly value: number; readonly label: string; readonly style?: 'solid' | 'dashed'; }
export interface TimelineBand { readonly start: number; readonly end: number; readonly label: string; readonly tone: 'safe' | 'uncertain' | 'failure' | 'neutral'; }
export interface TimelineChartProps {
  readonly title: string;
  readonly series: readonly TimelineSeries[];
  readonly thresholds?: readonly TimelineThreshold[];
  readonly bands?: readonly TimelineBand[];
  readonly cursorT?: number;
  readonly onCursorChange?: (t: number) => void;
  readonly yUnit: string;
}
const WIDTH = 720, HEIGHT = 220, LEFT = 64, RIGHT = 20, TOP = 24, BOTTOM = 42;
function bounds(values: readonly number[]): readonly [number, number] {
  let min = Number.POSITIVE_INFINITY, max = Number.NEGATIVE_INFINITY;
  for (const value of values) if (Number.isFinite(value)) { min = Math.min(min,value); max = Math.max(max,value); }
  return min === Number.POSITIVE_INFINITY ? [0,1] : [min,max];
}
interface TableRow { readonly time: number; readonly values: Readonly<Record<string, number | undefined>>; }

/** Lightweight timeline with a keyboard cursor and an accessible data-table alternative. */
export function TimelineChart({ title, series, thresholds = [], bands = [], cursorT, onCursorChange, yUnit }: TimelineChartProps) {
  const id = useId();
  const [showData, setShowData] = useState(false);
  const xDomain = useMemo(() => bounds(series.flatMap((line) => [...line.t])), [series]);
  const yDomain = useMemo(() => bounds([...series.flatMap((line) => [...line.y]), ...thresholds.map((line) => line.value)]), [series,thresholds]);
  const x = useMemo(() => linearScale(xDomain,[LEFT,WIDTH-RIGHT]), [xDomain]);
  const y = useMemo(() => linearScale(yDomain,[HEIGHT-BOTTOM,TOP]), [yDomain]);
  const paths = useMemo(() => series.map((line) => {
    let valid = false;
    return line.y.map((value,index) => { const t = line.t[index]; if (t === undefined || !Number.isFinite(value) || !Number.isFinite(t)) { valid = false; return ''; } const segment = `${valid ? 'L' : 'M'}${String(x(t))},${String(y(value))}`; valid = true; return segment; }).join(' ');
  }), [series,x,y]);
  const tableRows: TableRow[] = showData ? (series[0]?.t ?? []).map((time,index) => ({time,values:Object.fromEntries(series.map((line) => [line.label,line.y[index]]))})) : [];
  const tableColumns: StatColumn<TableRow>[] = [{key:'time',header:'Time',unit:'s',align:'right',sortable:true}, ...series.map((line):StatColumn<TableRow> => ({key:'values',header:line.label,unit:yUnit,align:'right',format:(_,row) => row.values[line.label] === undefined ? '—' : String(row.values[line.label])}))];
  function hover(event: PointerEvent<SVGSVGElement>) {
    if (onCursorChange === undefined) return;
    const rect = event.currentTarget.getBoundingClientRect(); if (!rect.width) return;
    const svgX = (event.clientX - rect.left) / rect.width * WIDTH;
    const t = linearScale([LEFT,WIDTH-RIGHT],xDomain)(svgX);
    onCursorChange(Math.max(xDomain[0],Math.min(xDomain[1],t)));
  }
  return <section className={styles.root} aria-labelledby={id}>
    <div className={styles.header}><h3 id={id}>{title}</h3><button type="button" onClick={() => { setShowData((current) => !current); }} aria-expanded={showData}>{showData ? 'Hide data table' : 'Show data table'}</button></div>
    <svg viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} className={styles.chart} aria-hidden="true" onPointerMove={hover}>
      {bands.map((band,index) => <g key={index}><rect x={x(band.start)} y={TOP} width={Math.max(0,x(band.end)-x(band.start))} height={HEIGHT-TOP-BOTTOM} className={styles[band.tone]} /><text x={x(band.start)+4} y={TOP+12} className={styles['band-label']}>{band.label}</text></g>)}
      {niceTicks(yDomain[0],yDomain[1]).map((value) => <g key={value}><line x1={LEFT} x2={WIDTH-RIGHT} y1={y(value)} y2={y(value)} className={styles.grid} /><text x={LEFT-8} y={y(value)+4} textAnchor="end">{value}</text></g>)}
      {niceTicks(xDomain[0],xDomain[1]).map((value) => <text key={value} x={x(value)} y={HEIGHT-BOTTOM+20} textAnchor="middle">{value}</text>)}
      <text x={WIDTH-RIGHT} y={HEIGHT-4} textAnchor="end">Time (s)</text><text x={LEFT} y={TOP-8}>{yUnit}</text>
      {thresholds.map((threshold,index) => <g key={index} data-threshold={threshold.value}><line x1={LEFT} x2={WIDTH-RIGHT} y1={y(threshold.value)} y2={y(threshold.value)} className={styles.threshold} /><text x={WIDTH-RIGHT} y={y(threshold.value)-4} textAnchor="end">{threshold.label}: {threshold.value} {yUnit}</text></g>)}
      {series.map((line,index) => <path key={line.label} d={paths[index]} className={index === 0 ? styles.primary : styles.secondary} strokeDasharray={line.style === 'dashed' ? '6 4' : undefined} />)}
      {cursorT === undefined ? null : <line data-testid="timeline-cursor" data-time={cursorT} x1={x(cursorT)} x2={x(cursorT)} y1={TOP} y2={HEIGHT-BOTTOM} className={styles.cursor} />}
    </svg>
    <label className={styles.scrubber}>Inspect time <input type="range" aria-label={`${title} inspection time`} min={xDomain[0]} max={xDomain[1]} step="any" value={Math.max(xDomain[0],Math.min(xDomain[1],cursorT ?? xDomain[0]))} onChange={(event) => { onCursorChange?.(event.currentTarget.valueAsNumber); }} /><output>{(cursorT ?? xDomain[0]).toFixed(2)} s</output></label>
    <p className={styles.legend}>{series.map((line) => `${line.label}${line.style === 'dashed' ? ' (dashed)' : ''}`).join(' · ')}</p>
    {showData ? <StatTable rows={tableRows} columns={tableColumns} rowKey={(row) => String(row.time)} caption={`${title} recorded values`} /> : null}
  </section>;
}
