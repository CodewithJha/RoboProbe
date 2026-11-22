import { ExportReportButton } from '../../reports/ExportReportButton';

export function ReportExport({ experimentId }: { experimentId: string }) {
  return (
    <section aria-label="Experiment report">
      <ExportReportButton kind="experiment" id={experimentId} />
    </section>
  );
}