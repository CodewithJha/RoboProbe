import { campaignColumns } from '../campaigns/campaignColumns';
import { Link } from 'react-router-dom';
import { useCampaigns, useModes, useWorkers, useMeta, type Campaign } from '../../api/hooks';
import { EmptyState, SpecimenTag, StatTable } from '../../components';
import { ProblemView } from '../../app/ProblemView';
import { useRuntimeConfig } from '../../app/contexts';
import { isOnline, limit } from '../../lib/workers';
import styles from './BenchPage.module.css';

function RecentCases({ campaign }: { campaign: Campaign }) {
  const modes = useModes(campaign.id);
  return (
    <div className={styles['tags']}>
      {modes.data?.items.map((mode) => (
        <SpecimenTag
          key={mode.id}
          kind="mode"
          id={mode.code}
          verdict="FAIL"
          label={mode.label}
          to={`/campaigns/${campaign.id}/casebook`}
        />
      ))}
    </div>
  );
}
export function Component() {
  const config = useRuntimeConfig();
  const campaigns = useCampaigns({ limit: config.benchRecentLimit });
  const running = useCampaigns({ status: 'RUNNING' });
  const paused = useCampaigns({ status: 'PAUSED' });
  const workers = useWorkers();
  const meta = useMeta();
  const header = (
    <header className={styles['header']}>
      <div>
        <p className="page-label">Field Notebook / Overview</p>
        <h1>Bench</h1>
        <p className="page-description">
          Your testing campaigns, their discoveries, and the workers behind them.
        </p>
      </div>
      <Link className={styles['primary']} to="/campaigns/new">
        New campaign
      </Link>
    </header>
  );

  if (campaigns.isPending)
    return (
      <section aria-busy="true" className={[styles['page'], styles['loading']].join(' ')}>
        {header}
        <p role="status">Opening your campaigns…</p>
        <div className={styles['skeleton']} aria-hidden="true">
          <div />
          <div />
          <div />
        </div>
      </section>
    );
  if (campaigns.isError) return <ProblemView error={campaigns.error} />;
  const rows = campaigns.data.pages
    .flatMap((page) => page.items)
    .sort((a, b) => (b.created_at ?? b.id).localeCompare(a.created_at ?? a.id));
  const active = [...(running.data?.pages ?? []), ...(paused.data?.pages ?? [])].flatMap(
    (page) => page.items,
  );
  const online =
    workers.data?.items.filter((worker) =>
      isOnline(worker, limit(meta.data, 'heartbeat_timeout_s')),
    ) ?? [];
  const counts = new Map<string, number>();
  online.forEach((worker) => {
    counts.set(worker.backend, (counts.get(worker.backend) ?? 0) + 1);
  });
  return (
    <section className={styles['page']}>
      {header}
      <section className={styles['workbench']} aria-label="Workbench summary">
        <h2>Workbench</h2>
        {workers.isPending ? (
          <p role="status">Checking workers…</p>
        ) : workers.isError ? (
          <p>
            Worker health could not be loaded. <Link to="/workbench">Open Workbench</Link>
          </p>
        ) : (
          <>
            <strong>{online.length} workers online</strong>
            {[...counts].map(([backend, count]) => (
              <span key={backend}>
                {backend} · {count}
              </span>
            ))}
            {online.length === 0 ? <p>Start a worker before launching a campaign.</p> : null}
          </>
        )}
        <Link to="/workbench">View workers</Link>
      </section>
      {rows.length === 0 ? (
        <EmptyState
          title="No campaigns yet"
          body="Start one to let RoboProbe hunt for failures."
          action={{ label: 'New campaign', to: '/campaigns/new' }}
        />
      ) : (
        <>
          <section>
            <h2>Active campaigns</h2>
            <div className={styles['active']}>
              {active.map((row) => (
                <article key={row.id} className={styles['campaign']}>
                  <div className={styles['card-heading']}>
                    <Link to={`/campaigns/${row.id}/console`}>{row.name}</Link>
                    <span>{row.status}</span>
                  </div>
                  <p className={styles['meta']}>
                    {row.strategy.id} · {row.backend}
                  </p>
                  <progress
                    aria-label={`${row.name} progress`}
                    value={row.counts?.['done'] ?? 0}
                    max={row.budget}
                  />
                  <p>
                    {row.counts?.['done'] ?? 0} / {row.budget} runs · {row.counts?.['fail'] ?? 0}{' '}
                    failures · {row.modes_found} cases
                  </p>
                </article>
              ))}
            </div>
            {running.isPending || paused.isPending ? (
              <p role="status">Loading active campaigns…</p>
            ) : null}
            {running.isError || paused.isError ? (
              <p role="alert">Active campaigns could not be loaded.</p>
            ) : null}
            {running.hasNextPage ? (
              <button
                type="button"
                disabled={running.isFetchingNextPage}
                onClick={() => {
                  void running.fetchNextPage();
                }}
              >
                More running campaigns
              </button>
            ) : null}
            {paused.hasNextPage ? (
              <button
                type="button"
                disabled={paused.isFetchingNextPage}
                onClick={() => {
                  void paused.fetchNextPage();
                }}
              >
                More paused campaigns
              </button>
            ) : null}
            {!running.isPending &&
            !paused.isPending &&
            !running.isError &&
            !paused.isError &&
            active.length === 0 ? (
              <p className={styles['muted']}>
                No active campaigns. Your completed work is recorded below.
              </p>
            ) : null}
          </section>
          <section>
            <h2>Recent campaigns</h2>
            <StatTable
              rows={rows.slice(0, config.benchRecentLimit)}
              columns={campaignColumns}
              caption="Recent campaigns"
              rowKey={(row) => row.id}
            />
          </section>
          <section>
            <h2>Recent cases</h2>
            {rows.slice(0, config.benchRecentCaseCampaigns).map((row) => (
              <RecentCases key={row.id} campaign={row} />
            ))}
            <p className={styles['muted']}>
              Cases from the most recent {config.benchRecentCaseCampaigns} campaigns.
            </p>
          </section>
        </>
      )}
      {campaigns.hasNextPage ? (
        <button
          type="button"
          disabled={campaigns.isFetchingNextPage}
          onClick={() => void campaigns.fetchNextPage()}
        >
          Load more campaigns
        </button>
      ) : null}
    </section>
  );
}
