import { lazy, Suspense, useState } from 'react';
import { useParams } from 'react-router-dom';
import { CasebookGrid } from './cards/CasebookGrid';

const Insights = lazy(async () => ({
  default: (await import('./insights/InsightsPanel')).InsightsPanel,
}));

export function Component() {
  const { id } = useParams();
  const [showInsights, setShowInsights] = useState(false);
  if (!id) return null;
  return (
    <>
      <CasebookGrid campaignId={id} />
      <details
        onToggle={(event) => {
          setShowInsights(event.currentTarget.open);
        }}
      >
        <summary>Campaign insights</summary>
        {showInsights ? (
          <Suspense fallback={<p role="status">Loading insights…</p>}>
            <Insights campaignId={id} />
          </Suspense>
        ) : null}
      </details>
    </>
  );
}
