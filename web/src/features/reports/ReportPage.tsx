import { useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ProblemView } from '../../app/ProblemView';
import { useReportContent, useReportJob } from './useReportJob';

const reportPolicy =
  '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">';

function previewDocument(html: string): string {
  const head = /<head(?:\s[^>]*)?>/i;
  return head.test(html)
    ? html.replace(head, (openingTag) => openingTag + reportPolicy)
    : `<!doctype html>${reportPolicy}${html}`;
}

function downloadReport(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

export function Component() {
  const { id = '' } = useParams();
  const job = useReportJob(id);
  const content = useReportContent(id, job.data?.status === 'COMPLETED');
  const frame = useRef<HTMLIFrameElement>(null);
  if (job.isError) return <ProblemView error={job.error} />;
  if (job.isPending) return <p role="status">Loading report…</p>;
  const status = job.data.status;
  if (status === 'FAILED') return <p role="alert">Report generation failed.</p>;
  if (status !== 'COMPLETED') return <p role="status">Report is still generating…</p>;
  if (content.isError) return <ProblemView error={content.error} />;
  if (content.isPending) return <p role="status">Loading report content…</p>;
  const { blob, html } = content.data;
  const bundle = job.data.kind === 'bundle';
  return (
    <section>
      <p className="page-label">RoboProbe / Report</p>
      <h1>Exported report</h1>
      <p>
        {html && (
          <button
            type="button"
            onClick={() => {
              frame.current?.contentWindow?.print();
            }}
          >
            Print
          </button>
        )}{' '}
        <button
          type="button"
          onClick={() => {
            downloadReport(blob, `report-${id}.${bundle ? 'tar.zst' : 'html'}`);
          }}
        >
          {bundle ? 'Download archive' : 'Download HTML'}
        </button>{' '}
        <Link to="/">Back to Bench</Link>
      </p>
      {html && (
        <iframe
          ref={frame}
          title="Report preview"
          srcDoc={previewDocument(html)}
          sandbox="allow-same-origin allow-modals"
          style={{ border: '1px solid var(--margin-line)', width: '100%', minHeight: '70vh' }}
        />
      )}
    </section>
  );
}
