import { useState } from 'react';
import { Link, useRouteError } from 'react-router-dom';
import { ProblemError } from '../api/client';
export function ProblemView({ error }: { error: unknown }) {
  const [copyStatus, setCopyStatus] = useState('Copy trace ID');
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
            if (!window.isSecureContext) {
              setCopyStatus('Select and copy trace ID');
              return;
            }
            void navigator.clipboard
              .writeText(problem.traceId ?? '')
              .then(() => {
                setCopyStatus('Trace ID copied');
              })
              .catch(() => {
                setCopyStatus('Select and copy trace ID');
              });
          }}
        >
          {`${copyStatus} ${problem.traceId}`}
        </button>
      ) : null}
      <Link to="/">Return to Bench</Link>
    </section>
  );
}
export function RouteError() {
  return <ProblemView error={useRouteError()} />;
}
