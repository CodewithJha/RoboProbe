import { useState } from 'react';
import { ConditionStrip } from './ConditionStrip/ConditionStrip';
import { EmptyState } from './EmptyState/EmptyState';
import { RobustnessBar } from './RobustnessBar/RobustnessBar';
import { SpecimenTag } from './SpecimenTag/SpecimenTag';
import { Spine, type SpineRun } from './Spine/Spine';
import { StatTable, type StatColumn } from './StatTable/StatTable';
import { VerdictNotch } from './VerdictNotch/VerdictNotch';
import styles from './ComponentGallery.module.css';

const runs: SpineRun[] = Array.from({ length: 10000 }, (_, index) => ({
  id: `run-${String(index + 1)}`,
  ordinal: index + 1,
  verdict: index % 3 === 0 ? 'FAIL' : 'PASS',
}));
const columns: StatColumn<SpineRun>[] = [
  { key: 'ordinal', header: 'Run', align: 'right', sortable: true },
  { key: 'verdict', header: 'Verdict', sortable: true },
  { key: 'id', header: 'Identifier' },
];

/** Development-only gallery. Its route must be gated by import.meta.env.DEV at the router. */
export function ComponentGallery() {
  const [selected, setSelected] = useState('run-1');
  return (
    <div className={styles.gallery}>
      <header>
        <h1>Field Notebook components</h1>
        <p>Shared visual instruments for runs, cases and operating envelopes.</p>
      </header>
      <section className={styles.section}>
        <h2>Conditions and specimen identity</h2>
        <ConditionStrip
          values={[0.9, 0.1, 0.8, 0.5, 0.4, 0.6]}
          labels={['Speed', 'Light', 'Noise', 'Friction', 'Clearance', 'Delay']}
          formatted={['0.42 m/s', '12 lux', '0.08 m', '0.7', '0.18 m', '120 ms']}
          highlight={[0, 1, 2]}
          size="md"
        />
        <SpecimenTag kind="run" id="087" verdict="FAIL" label="Low-light collision" />
        <div className={styles.row}>
          <VerdictNotch verdict="PASS" /> PASS <VerdictNotch verdict="FAIL" /> FAIL{' '}
          <VerdictNotch verdict="INVALID" /> INVALID
        </div>
      </section>
      <section className={styles.section}>
        <h2>Robustness</h2>
        <div className={styles.row}>
          <RobustnessBar value={-0.37} />
          <RobustnessBar value={0} />
          <RobustnessBar value={0.42} />
        </div>
      </section>
      <section className={styles.section}>
        <h2>10,000-run spine</h2>
        <p>
          Selected: <output>{selected}</output>. Use arrow keys, Home or End.
        </p>
        <Spine runs={runs} onSelect={setSelected} selectedId={selected} />
      </section>
      <section className={styles.section}>
        <h2>Statistics</h2>
        <StatTable
          rows={runs}
          columns={columns}
          rowKey={(row) => row.id}
          caption="Campaign run statistics"
        />
      </section>
      <EmptyState
        title="No cases yet"
        body="Failures will appear here as the campaign runs. Start a campaign to explore its failure modes."
        action={{ label: 'New campaign', to: '/campaigns/new' }}
      />
    </div>
  );
}
