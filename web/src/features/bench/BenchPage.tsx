import { FeaturePage } from '../../app/FeaturePage';
export function Component() {
  return (
    <FeaturePage
      title="Bench"
      description="Your campaigns, workers and recent cases in one notebook."
      action="New campaign"
      to="/campaigns/new"
    />
  );
}
