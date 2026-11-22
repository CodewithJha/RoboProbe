import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { stringify } from 'yaml';
import { useSpace, useValidateSpace } from '../../api/hooks';
import { ProblemView } from '../../app/ProblemView';
import { StatTable } from '../../components';
import { parameters } from '../../lib/spaceParameters';
import styles from './SpacePage.module.css';

export function Component() {
  const { id = '', version = '' } = useParams();
  const space = useSpace(id, version);
  const validate = useValidateSpace();
  const [draft, setDraft] = useState('');
  if (space.isError) return <ProblemView error={space.error} />;
  if (space.isPending) return <p role="status">Loading space…</p>;
  const detail = space.data;
  const yaml = stringify(detail.definition);
  const rows = parameters(detail.definition);
  return (
    <section className={styles['layout']}>
      <p className="page-label">
        <Link to="/spaces">Spaces</Link> / {detail.name}
      </p>
      <h1>{detail.name}</h1>
      <p className="page-description">{detail.description || `Version ${detail.version}`}</p>
      <section>
        <h2>Definition</h2>
        <pre className={styles['yaml']}>{yaml}</pre>
      </section>
      <section>
        <h2>Parameters</h2>
        <StatTable
          caption="Space parameters"
          rows={rows}
          rowKey={(row) => row.id}
          emptyText="No parameters in this definition."
          columns={[
            { key: 'name', header: 'Name', sortable: true },
            { key: 'unit', header: 'Unit' },
            { key: 'type', header: 'Type' },
            {
              key: 'low',
              header: 'Range',
              format: (_value, row) =>
                row.low === undefined || row.high === undefined
                  ? '—'
                  : `${String(row.low)} … ${String(row.high)}`,
            },
            { key: 'scale', header: 'Scale' },
            { key: 'nominal', header: 'Nominal', align: 'right' },
            {
              key: 'enabled',
              header: 'Enabled',
              format: (value) => (value ? 'yes' : 'no'),
            },
          ]}
        />
      </section>
      <section className={styles['panel']}>
        <h2>Validate YAML</h2>
        <label htmlFor="space-draft">Paste YAML to validate against the schema</label>
        <textarea
          id="space-draft"
          rows={8}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
        <button
          type="button"
          disabled={validate.isPending || !draft.trim()}
          onClick={() => {
            validate.mutate(draft);
          }}
        >
          Validate
        </button>
        {validate.isError ? <ProblemView error={validate.error} /> : null}
        {validate.data ? (
          <div role="status">
            {validate.data.valid ? <p>Valid ({validate.data.dimension ?? 0} dimensions).</p> : null}
            {validate.data.errors.map((error) => (
              <p key={`${error.pointer}:${error.message}`} className={styles['error']}>
                <code>{error.pointer || '/'}</code> — {error.message}
              </p>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
