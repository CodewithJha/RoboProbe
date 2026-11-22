import { Link, useParams } from 'react-router-dom';
import { useExperiment, useExperimentComparison } from '../../../api/hooks';
import { useRuntimeConfig } from '../../../app/contexts';
import { StatTable } from '../../../components';
import { number, summaries, text } from '../evidence';
import { ExperimentCharts } from './ExperimentCharts';
import { ReportExport } from './ReportExport';
import { ThreatsNotes } from './ThreatsNotes';

export function Component() {
  const { id = '' } = useParams();
  const { featureFlags } = useRuntimeConfig();
  const experiment = useExperiment(id);
  const comparison = useExperimentComparison(id);
  const data = comparison.data;
  const rows = data ? summaries(data) : [];
  const tests =
    data?.tests?.map((test, index) => ({
      index,
      metric: text(test['metric']),
      a: text(test['a']),
      b: text(test['b']),
      test: text(test['test']),
      p: number(test['p']),
      holm: number(test['p_holm']),
      a12: number(test['a12']),
      effect: text(test['effect']),
    })) ?? [];
  return (
    <article>
      <h1>Compare strategies</h1>
      <p>
        <Link to={`/trials/${id}`}>Experiment details</Link>
      </p>
      {data && featureFlags.reports && <ReportExport key={`report-${id}`} experimentId={id} />}
      {comparison.isPending && <p role="status">Loading comparison…</p>}
      {comparison.isError && <p role="alert">{comparison.error.message}</p>}
      {data && (
        <>
          <StatTable
            rows={rows}
            rowKey={(row) => JSON.stringify([row.strategy, row.metric])}
            caption="Strategy metrics"
            emptyText="No comparison results are available."
            columns={[
              { key: 'strategy', header: 'Strategy', sortable: true },
              { key: 'metric', header: 'Metric', sortable: true },
              { key: 'median', header: 'Median', align: 'right', sortable: true },
              {
                key: 'iqr',
                header: 'Interquartile range',
                sortable: false,
                format: (_, row) => row.iqr?.join('–') ?? '—',
              },
              {
                key: 'ci',
                header: '95% confidence interval',
                sortable: false,
                format: (_, row) => row.ci?.join('–') ?? '—',
              },
            ]}
          />
          <StatTable
            rows={tests}
            rowKey={(row) => String(row.index)}
            caption="Pairwise tests"
            emptyText="No pairwise tests are available."
            columns={[
              { key: 'metric', header: 'Metric', sortable: true },
              { key: 'a', header: 'Strategy A', sortable: true },
              { key: 'b', header: 'Strategy B', sortable: true },
              { key: 'test', header: 'Test', sortable: true },
              { key: 'p', header: 'p', align: 'right', sortable: true },
              { key: 'holm', header: 'p (Holm)', align: 'right', sortable: true },
              { key: 'a12', header: 'Â12', align: 'right', sortable: true },
              { key: 'effect', header: 'Effect', sortable: true },
            ]}
          />
        </>
      )}
      {data && <ExperimentCharts id={id} />}
      {experiment.data && <ThreatsNotes key={id} experiment={experiment.data} />}
      {experiment.isError && <p role="alert">Unable to load experiment notes.</p>}
    </article>
  );
}
