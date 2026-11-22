import { useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiUrl } from '../../api/client';
import { ProblemView } from '../../app/ProblemView';
import { useReportJob } from './useReportJob';

export function Component() {
  const { id = '' } = useParams();
  const job = useReportJob(id);
  const frame = useRef<HTMLIFrameElement>(null);
  const contentUrl = id ? apiUrl(`/reports/${id}/content`) : '';
  if (job.isError) return <ProblemView error={job.error} />;
  if (job.isPending) return <p role="status">Loading report…</p>;
  if (job.data?.status === 'FAILED') return <p role="alert">Report generation failed.</p>;
  if (job.data?.status !== 'COMPLETED') return <p role="status">Report is still generating…</p>;
  return (
    <section>
      <p className="page-label">RoboProbe / Report</p>
      <h1>Exported report</h1>
      <p>
        <button
          type="button"
          onClick={() => {
            frame.current?.contentWindow?.print();
          }}
        >
          Print
        </button>{' '}
        <a href={contentUrl} download={`report-${id}.html`}>
          Download HTML
        </a>{' '}
        <Link to="/">Back to Bench</Link>
      </p>
      <iframe
        ref={frame}
        title="Report preview"
        src={contentUrl}
        sandbox="allow-same-origin"
        style={{ border: '1px solid var(--margin-line)', width: '100%', minHeight: '70vh' }}
      />
    </section>
  );
}