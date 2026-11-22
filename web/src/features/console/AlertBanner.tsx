import { useState } from 'react';
import { skipToken, useQuery } from '@tanstack/react-query';
import styles from './Console.module.css';

export function AlertBanner({ campaignId }: { campaignId: string }) {
  const [dismissed, setDismissed] = useState<ReadonlySet<Record<string, unknown>>>(new Set());
  const alerts = useQuery<readonly Record<string, unknown>[]>({
    queryKey: ['alerts'],
    queryFn: skipToken,
  });
  return alerts.data
    ?.filter(
      (alert) =>
        (!alert['campaign_id'] || alert['campaign_id'] === campaignId) && !dismissed.has(alert),
    )
    .map((alert, index) => (
      <aside role="alert" className={styles['alert']} key={index}>
        <strong>{typeof alert['code'] === 'string' ? alert['code'] : 'Campaign alert'}</strong>
        <span>{typeof alert['message'] === 'string' ? alert['message'] : ''}</span>
        {alert['code'] === 'INFRA_UNHEALTHY' ? (
          <a href="https://github.com/CodewithJha/RoboProbe/blob/main/docs/30-operations-runbook.md#rb-01-campaign-auto-paused-with-infra_unhealthy">
            Read runbook RB-01
          </a>
        ) : null}
        <button
          type="button"
          onClick={() => {
            setDismissed((old) => new Set([...old, alert]));
          }}
        >
          Dismiss
        </button>
      </aside>
    ));
}
