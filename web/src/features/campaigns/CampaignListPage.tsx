import { FeaturePage } from '../../app/FeaturePage';
export function Component() {
  return (
    <FeaturePage
      title="Campaigns"
      description="Review active and recent testing campaigns."
      action="New campaign"
      to="/campaigns/new"
    />
  );
}
