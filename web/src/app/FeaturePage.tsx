import { Link } from 'react-router-dom';
/** Stable feature mount point while independent feature PRs land (T-085b). */
export function FeaturePage({
  title,
  description,
  action = 'Return to Bench',
  to = '/',
}: {
  title: string;
  description: string;
  action?: string;
  to?: string;
}) {
  return (
    <section className="feature-page">
      <p className="page-label">RoboProbe / Field Notebook</p>
      <h1>{title}</h1>
      <p className="page-description">{description}</p>
      <div className="feature-empty">
        <h2>This section is ready for its next entry</h2>
        <p>
          Connect to your RoboProbe API and use the campaign workflow to populate this notebook.
        </p>
        <Link to={to}>{action}</Link>
      </div>
    </section>
  );
}
