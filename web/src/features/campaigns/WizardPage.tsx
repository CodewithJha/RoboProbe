import { FeaturePage } from '../../app/FeaturePage';
export function Component() {
  return (
    <FeaturePage
      title="New campaign"
      description="Choose a space, robot backend, strategy and reproducible budget."
      action="Browse spaces"
      to="/spaces"
    />
  );
}
