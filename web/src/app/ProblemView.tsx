import { useState } from 'react';
import { Link, useRouteError } from 'react-router-dom';
import { ProblemError } from '../api/client';
export function ProblemView({ error }: { error: unknown }) {
  const [copied, setCopied] = useState(false);
  const problem = error instanceof ProblemError ? error : undefined;
  return (
    <section role="alert" className="problem-view">
      <h1>{problem?.title ?? 'Something went wrong'}</h1>
      <p>
        {problem?.detail ?? 'This page could not be loaded. Return to the Bench and try again.'}
      </p>
      {problem?.traceId ? (
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(problem.traceId ?? '').then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? 'Trace ID copied' : `Copy trace ID ${problem.traceId}`}
        </button>
      ) : null}
      <Link to="/">Return to Bench</Link>
    </section>
  );
}
export function RouteError() {
  return <ProblemView error={useRouteError()} />;
}
