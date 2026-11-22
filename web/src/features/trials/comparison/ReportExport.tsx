import { useMutation } from '@tanstack/react-query';
import { api, requireData } from '../../../api/client';
import { useCreateReport, useReportJob } from '../../../api/hooks';
import { useRuntimeConfig } from '../../../app/contexts';

export function ReportExport({ experimentId }: { experimentId: string }) {
  const { queryStaleTimeMs } = useRuntimeConfig();
  const create = useCreateReport();
  const jobId = create.data?.id ?? '';
  const job = useReportJob(jobId, queryStaleTimeMs);
  const status = job.data?.status ?? create.data?.status;
  const ready = status === 'COMPLETED' && !job.isError;
  const failed = status === 'FAILED' || status === 'ERROR';
  const running = create.isPending || (Boolean(jobId) && !job.isError && !ready && !failed);
  const download = useMutation({
    mutationFn: async (id: string) => {
      const result = await api.GET('/api/v1/reports/{report_id}/content', {
        params: { path: { report_id: id } },
        headers: { Accept: 'text/html' },
        parseAs: 'blob',
      });
      if (
        result.response.status !== 200 ||
        !result.response.headers.get('content-type')?.startsWith('text/html')
      ) {
        throw new Error('The report HTML is unavailable.');
      }
      const url = URL.createObjectURL(requireData(result));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `experiment-${experimentId}.html`;
      anchor.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
      }, 0);
    },
  });
  const error = create.error ?? job.error ?? download.error;

  return (
    <section aria-label="Experiment report">
      <button
        type="button"
        disabled={running || download.isPending}
        onClick={() => {
          download.reset();
          create.mutate({ kind: 'experiment', id: experimentId });
        }}
      >
        Export report
      </button>
      {running && <p role="status">Generating report…</p>}
      {ready && (
        <button
          type="button"
          disabled={download.isPending || create.isPending}
          onClick={() => {
            download.mutate(jobId);
          }}
        >
          {download.isPending ? 'Downloading report…' : 'Download HTML report'}
        </button>
      )}
      {error && <p role="alert">{error.message}</p>}
      {!error && failed && <p role="alert">Report generation failed.</p>}
    </section>
  );
}
