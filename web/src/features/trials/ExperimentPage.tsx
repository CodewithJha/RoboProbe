import { Link, useParams } from 'react-router-dom';
import { useExperiment } from '../../api/hooks';
import { StatTable } from '../../components';
import { cells, strategyNames } from './evidence';

export function Component() {
  const { id = '' } = useParams();
  const query = useExperiment(id);
  const experiment = query.data;
  const rows = experiment ? cells(experiment) : [];
  const completed = rows.filter((row) => row.status === 'COMPLETED').length;
  return (
    <article>
      <h1>Experiment</h1>
      <p>
        <Link to="/trials">All trials</Link>
      </p>
      {query.isPending && <p role="status">Loading experiment…</p>}
      {query.isError && <p role="alert">{query.error.message}</p>}
      {experiment && (
        <>
          <h2>{experiment.name}</h2>
          <p>
            {experiment.status} · {strategyNames(experiment.design).join(', ')}
          </p>
          <p>
            {completed} of {rows.length} campaign cells completed.
          </p>
          {rows.length > 0 && (
            <progress aria-label="Completed campaign cells" value={completed} max={rows.length} />
          )}
          <StatTable
            rows={rows}
            rowKey={(row) => row.id}
            caption="Experiment design cells"
            emptyText="No campaign cells have been created."
            columns={[
              { key: 'strategy', header: 'Strategy' },
              { key: 'seed', header: 'Seed', align: 'right' },
              { key: 'budget', header: 'Budget', align: 'right' },
              { key: 'status', header: 'Status' },
              {
                key: 'id',
                header: 'Campaign',
                format: (_, row) => (
                  <Link to={`/campaigns/${row.id}/console`}>
                    Open {row.strategy} campaign
                    {row.seed === undefined ? '' : ` (seed ${String(row.seed)})`}
                  </Link>
                ),
              },
            ]}
          />
          <p>
            <Link to={`/trials/${id}/comparison`}>Compare strategies</Link>
          </p>
        </>
      )}
    </article>
  );
}
