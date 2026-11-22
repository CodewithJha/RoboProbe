import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateReport } from '../../api/hooks';
import { useReportJob } from './useReportJob';

export function ExportReportButton({
  kind,
  id,
  label = 'Export report',
}: {
  kind: string;
  id: string;
  label?: string;
}) {
  const navigate = useNavigate();
  const create = useCreateReport();
  const jobId = create.data?.id ?? '';
  const job = useReportJob(jobId);
  const opened = useRef(false);
  const status = job.data?.status ?? (create.isSuccess ? create.data.status : undefined);
  const failed = status === 'FAILED' || status === 'ERROR';
  const ready = status === 'COMPLETED' && Boolean(jobId);
  const running = create.isPending || (Boolean(jobId) && !job.isError && !ready && !failed);
  const error = create.error ?? job.error;

  useEffect(() => {
    if (!ready || opened.current) return;
    opened.current = true;
    void navigate(`/reports/${jobId}`);
  }, [jobId, navigate, ready]);

  useEffect(() => {
    if (!jobId) opened.current = false;
  }, [jobId]);

  return (
    <>
      <button
        type="button"
        disabled={running}
        onClick={() => {
          opened.current = false;
          create.mutate({ kind, id });
        }}
      >
        {label}
      </button>
      {running ? <p role="status">Generating report…</p> : null}
      {error ? <p role="alert">{error.message}</p> : null}
      {!error && failed ? <p role="alert">Report generation failed.</p> : null}
    </>
  );
}
