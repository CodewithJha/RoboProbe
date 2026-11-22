import { useId } from 'react';
import type { Schema } from '../../../api/client';
import styles from '../Console.module.css';

import { prediction, rationaleFor, record } from './rationale';

export function RationalePopover({ run }: { run: Schema['RunOut'] }) {
  const id = useId();
  const rationale = rationaleFor(run);
  const nearest = record(rationale['nearest_case']);
  const fields: [string, string][] = [];
  const phase = rationale['phase'] ?? run.phase;
  const acquisition = rationale['acquisition_value'];
  const name = rationale['acquisition_name'];
  if (typeof phase === 'string' && phase) fields.push(['Phase', phase]);
  const estimate = prediction(rationale);
  if (estimate) fields.push(['Predicted μ ± σ', estimate]);
  if (typeof acquisition === 'number')
    fields.push([
      'Acquisition',
      `${typeof name === 'string' ? `${name} · ` : ''}${acquisition.toFixed(2)}`,
    ]);
  if (typeof nearest['code'] === 'string')
    fields.push([
      'Nearest known case',
      `${nearest['code']}${typeof nearest['distance'] === 'number' ? ` · ${nearest['distance'].toFixed(2)}` : ''}`,
    ]);
  if (typeof rationale['epsilon_explore'] === 'boolean')
    fields.push(['ε-explore', rationale['epsilon_explore'] ? 'Yes' : 'No']);
  if (!fields.length) return null;
  return (
    <>
      <button type="button" popoverTarget={id}>
        Why this scenario?
      </button>
      <div
        id={id}
        role="region"
        aria-label="Selection rationale"
        popover="auto"
        className={styles['rationale']}
      >
        <strong>Selection rationale</strong>
        <dl>
          {fields.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <button type="button" popoverTarget={id} popoverTargetAction="hide">
          Close rationale
        </button>
      </div>
    </>
  );
}
