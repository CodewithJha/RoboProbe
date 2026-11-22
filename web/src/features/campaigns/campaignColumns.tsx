import { Link } from 'react-router-dom';
import type { Campaign } from '../../api/hooks';
import type { StatColumn } from '../../components';

export const campaignColumns: readonly StatColumn<Campaign>[] = [
  {
    key: 'name',
    header: 'Campaign',
    sortable: true,
    format: (_value, row) => <Link to={`/campaigns/${row.id}/console`}>{row.name}</Link>,
  },
  { key: 'strategy', header: 'Strategy', format: (_value, row) => row.strategy.id },
  { key: 'backend', header: 'Backend', sortable: true },
  { key: 'status', header: 'Status', sortable: true },
  {
    key: 'counts',
    header: 'Runs / fails',
    format: (_value, row) =>
      `${String(row.counts?.['done'] ?? 0)} / ${String(row.counts?.['fail'] ?? 0)}`,
  },
  { key: 'modes_found', header: 'Cases', align: 'right', sortable: true },
  { key: 'first_failure_at', header: 'First failure', align: 'right', sortable: true },
  {
    key: 'created_at',
    header: 'Started',
    format: (_value, row) =>
      row.started_at ? new Date(row.started_at).toLocaleString() : 'Not started',
  },
];
