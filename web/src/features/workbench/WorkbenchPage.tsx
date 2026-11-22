import { useMeta, useWorkers } from '../../api/hooks';
import type { Schema } from '../../api/client';
import { ProblemView } from '../../app/ProblemView';
import { useNumberLocale } from '../../lib/NumberLocaleProvider';
import { formatDuration } from '../../lib/format';
import { heartbeatAgeSeconds } from '../../lib/heartbeat';
import { limit } from '../../lib/workers';
import { StatTable } from '../../components';

function heartbeatCell(
  worker: Schema['WorkerOut'],
  timeout: number | undefined,
  locale: string | undefined,
): { text: string; stale: boolean } {
  const age = heartbeatAgeSeconds(worker.last_heartbeat);
  const text = age === undefined ? '—' : formatDuration(age * 1000, { locale });
  const stale = timeout !== undefined && age !== undefined && age > timeout;
  return { text, stale };
}

export function Component() {
  const workers = useWorkers();
  const meta = useMeta();
  const { choice } = useNumberLocale();
  const locale = choice === 'system' ? undefined : choice;
  const timeout = limit(meta.data, 'heartbeat_timeout_s');
  if (workers.isError) return <ProblemView error={workers.error} />;
  const rows = workers.data?.items ?? [];
  return (
    <section>
      <p className="page-label">RoboProbe / Workbench</p>
      <h1>Workers</h1>
      <p className="page-description">Live worker health reported by the orchestrator.</p>
      {workers.isPending ? <p role="status">Loading workers…</p> : null}
      <StatTable
        caption="Workers"
        rows={rows}
        rowKey={(row) => row.id}
        emptyText="No workers are registered yet."
        columns={[
          { key: 'backend', header: 'Backend', sortable: true },
          { key: 'status', header: 'Status', sortable: true },
          {
            key: 'id',
            header: 'Current run',
            format: (_value, row) => (row.status === 'BUSY' ? 'In progress' : '—'),
          },
          {
            key: 'last_heartbeat',
            header: 'Heartbeat age',
            align: 'right',
            format: (_value, row) => {
              const { text, stale } = heartbeatCell(row, timeout, locale);
              return stale ? <strong title="Heartbeat is stale">{text}</strong> : text;
            },
          },
          { key: 'version', header: 'Version' },
        ]}
      />
    </section>
  );
}
