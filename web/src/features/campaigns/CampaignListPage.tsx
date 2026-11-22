import { Link } from 'react-router-dom';
import { useCampaigns } from '../../api/hooks';
import { ProblemView } from '../../app/ProblemView';
import { EmptyState, StatTable } from '../../components';
import { campaignColumns } from './campaignColumns';

export function Component() {
  const result = useCampaigns();
  if (result.isError && !result.data) return <ProblemView error={result.error} />;
  const rows = result.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <section>
      <h1>Campaigns</h1>
      <Link to="/campaigns/new">New campaign</Link>
      {result.isPending ? <p role="status">Loading campaigns…</p> : null}
      {!result.isPending && !rows.length ? (
        <EmptyState title="No campaigns yet" body="Create a campaign to populate this list." />
      ) : null}
      {rows.length ? (
        <StatTable
          caption="Campaigns"
          rows={rows}
          columns={campaignColumns}
          rowKey={(row) => row.id}
        />
      ) : null}
      {result.isFetchNextPageError ? <p role="alert">The next page could not be loaded.</p> : null}
      {result.hasNextPage ? (
        <button
          type="button"
          disabled={result.isFetchingNextPage}
          onClick={() => {
            void result.fetchNextPage();
          }}
        >
          {result.isFetchingNextPage ? 'Loading…' : 'Load more campaigns'}
        </button>
      ) : null}
    </section>
  );
}
