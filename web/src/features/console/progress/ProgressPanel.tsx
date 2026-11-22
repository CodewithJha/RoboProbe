import type { Schema } from '../../../api/client';
import { VerdictNotch, type Verdict } from '../../../components';
import styles from '../Console.module.css';

const verdicts: readonly Verdict[] = ['PASS', 'FAIL', 'INVALID'];

export function ProgressPanel({
  counts,
  budget,
  phase,
}: {
  counts: Record<string, number>;
  budget: number;
  phase?: string;
}) {
  const done = counts['done'] ?? 0;
  return (
    <section className={styles['card']} aria-label="Campaign progress">
      <h2>Progress</h2>
      <p role="status">
        {done} / {budget} runs
      </p>
      <progress aria-label="Completed runs" value={done} max={budget} />
      <ul className={styles['counts']}>
        {verdicts.map((verdict) => (
          <li key={verdict}>
            <VerdictNotch verdict={verdict} />
            <span aria-hidden="true">{verdict}</span> {counts[verdict.toLowerCase()] ?? 0}
          </li>
        ))}
      </ul>
      {phase ? <p>Phase · {phase}</p> : null}
    </section>
  );
}

export function DiscoveryCurve({
  curve,
  done,
}: {
  curve: Schema['CampaignProgress']['discovery_curve'];
  done: number;
}) {
  const points = (curve ?? []).flatMap((point) => {
    const runs = point['run_ordinal'];
    const cases = point['unique_modes'];
    return typeof runs === 'number' && typeof cases === 'number' ? [{ runs, cases }] : [];
  });
  const maxRuns = Math.max(done, points.at(-1)?.runs ?? 0, 1);
  const maxCases = Math.max(points.at(-1)?.cases ?? 0, 1);
  const endpoint = points.at(-1)?.cases ?? 0;
  const x = (runs: number) => 35 + (445 * runs) / maxRuns;
  const y = (cases: number) => 135 - (115 * cases) / maxCases;
  const path = [
    'M 35 135',
    ...points.map((point) => `H ${String(x(point.runs))} V ${String(y(point.cases))}`),
    'H 480',
  ].join(' ');
  return (
    <section className={styles['card']} aria-label="Campaign discovery">
      <h2>Discovery curve</h2>
      <svg
        role="img"
        aria-label={`${String(endpoint)} unique cases across ${String(done)} completed runs`}
        viewBox="0 0 500 165"
        className={styles['chart']}
      >
        <path d="M 35 15 V 135 H 480" stroke="currentColor" fill="none" />
        <path d={path} className={styles['curve']} fill="none" />
        <text x="30" y="25" textAnchor="end">
          {maxCases}
        </text>
        <text x="30" y="140" textAnchor="end">
          0
        </text>
        <text x="480" y="156" textAnchor="end">
          {maxRuns} runs
        </text>
      </svg>
    </section>
  );
}
