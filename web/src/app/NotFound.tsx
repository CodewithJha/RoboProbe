import { Link } from 'react-router-dom';
export function NotFound() {
  return (
    <section className="feature-page">
      <h1>Page not found</h1>
      <p className="page-description">This notebook entry could not be found.</p>
      <p>
        <Link to="/">Return to Bench</Link>
      </p>
    </section>
  );
}
