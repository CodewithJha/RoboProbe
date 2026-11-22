import { Link } from 'react-router-dom';
import { useExperiments } from '../../api/hooks';
import { StatTable } from '../../components';
import { asRecord, cells, number, strategyNames } from './evidence';

export function Component() {
  const query = useExperiments();
  const rows =
    query.data?.pages
      .flatMap((page) => page.items)
      .map((experiment) => {
        const design = experiment.design;
        const listed = cells(experiment);
        const completed =
          experiment.progress?.completed ??
          listed.filter((cell) => cell.status === 'COMPLETED').length;
        const total = experiment.progress?.total ?? listed.length;
        return {
          id: experiment.id,
          name: experiment.name,
          strategies: strategyNames(design).join(', ') || '—',
          seeds: number(asRecord(design['seeds'])['count']),
          budget: number(design['budget']),
          status: experiment.status,
          progress: total || experiment.progress ? `${String(completed)} / ${String(total)}` : '—',
        };
      }) ?? [];
  return (
    <article>
      <h1>Trials</h1>
      <p>
        Create experiments with <code>roboprobe experiment run</code>.
      </p>
      {query.isPending && <p role="status">Loading experiments…</p>}
      {query.isError && <p role="alert">{query.error.message}</p>}
      {query.data && (
        <StatTable
          rows={rows}
          rowKey={(row) => row.id}
          caption="Experiments"
          emptyText="No experiments are registered."
          columns={[
            {
              key: 'name',
              header: 'Experiment',
              format: (_, row) => <Link to={`/trials/${row.id}`}>{row.name}</Link>,
            },
            { key: 'strategies', header: 'Strategies' },
            { key: 'seeds', header: 'Seeds', align: 'right' },
            { key: 'budget', header: 'Budget', align: 'right' },
            { key: 'status', header: 'Status' },
            { key: 'progress', header: 'Completed cells' },
          ]}
        />
      )}
      {query.hasNextPage && (
        <button
          type="button"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          Load more experiments
        </button>
      )}
    </article>
  );
}
