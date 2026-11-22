import { Link } from 'react-router-dom';
import { useSpaces } from '../../api/hooks';
import { ProblemView } from '../../app/ProblemView';
import { EmptyState, StatTable } from '../../components';

export function Component() {
  const spaces = useSpaces();
  if (spaces.isError && !spaces.data) return <ProblemView error={spaces.error} />;
  const rows = spaces.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <section>
      <p className="page-label">RoboProbe / Spaces</p>
      <h1>Scenario spaces</h1>
      <p className="page-description">Registered scenario spaces and their canonical versions.</p>
      {spaces.isPending ? <p role="status">Loading spaces…</p> : null}
      {!spaces.isPending && !rows.length ? (
        <EmptyState title="No spaces yet" body="Register a space through the API to list it here." />
      ) : (
        <StatTable
          caption="Scenario spaces"
          rows={rows}
          rowKey={(row) => `${row.id}:${row.version}`}
          columns={[
            {
              key: 'name',
              header: 'Name',
              sortable: true,
              format: (_value, row) => (
                <Link to={`/spaces/${row.id}/${row.version}`}>{row.name}</Link>
              ),
            },
            { key: 'id', header: 'Id', sortable: true },
            { key: 'version', header: 'Version', sortable: true },
            { key: 'schema_version', header: 'Schema', align: 'right', sortable: true },
          ]}
        />
      )}
      {spaces.hasNextPage ? (
        <button
          type="button"
          disabled={spaces.isFetchingNextPage}
          onClick={() => {
            void spaces.fetchNextPage();
          }}
        >
          Load more spaces
        </button>
      ) : null}
    </section>
  );
}