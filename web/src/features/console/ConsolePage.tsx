import { parameters } from '../../lib/spaceParameters';
import { useParams } from 'react-router-dom';
import { useCampaign, useCampaignProgress, useRuns, useSpace } from '../../api/hooks';
import { ProblemView } from '../../app/ProblemView';
import { AlertBanner } from './AlertBanner';
import { CampaignHeader } from './header/CampaignHeader';
import { DiscoveryCurve, ProgressPanel } from './progress/ProgressPanel';
import { EntryStream } from './stream/EntryStream';
import styles from './Console.module.css';

export function Component() {
  const { id = '' } = useParams();
  const campaign = useCampaign(id);
  const progress = useCampaignProgress(id);
  const reference = campaign.data?.space;
  const space = useSpace(reference?.id ?? '', reference?.version ?? '');
  const runs = useRuns(id, { sort: '-ordinal' });

  if (campaign.isError) return <ProblemView error={campaign.error} />;
  if (!campaign.data) return <p role="status">Loading campaign…</p>;
  const counts = progress.data?.counts ?? campaign.data.counts ?? {};
  const phase = runs.data?.pages[0]?.items[0]?.phase;
  return (
    <section className={styles['page']}>
      <CampaignHeader campaign={campaign.data} />
      <AlertBanner key={`alerts-${id}`} campaignId={id} />
      <div className={styles['summary']}>
        <ProgressPanel
          counts={counts}
          budget={campaign.data.budget}
          {...(phase ? { phase } : {})}
        />
        <DiscoveryCurve curve={progress.data?.discovery_curve} done={counts['done'] ?? 0} />
      </div>
      {progress.isError ? <ProblemView error={progress.error} /> : null}
      <EntryStream
        key={`stream-${id}`}
        runs={runs}
        parameters={parameters(space.data?.definition)}
      />
    </section>
  );
}
