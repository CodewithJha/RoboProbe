import { useRuntimeConfig } from '../../app/contexts';
import { useReportJob as useReportJobQuery } from '../../api/hooks';

/** Poll an active report job until it leaves the running states (T-113b). */
export function useReportJob(id: string) {
  const { queryStaleTimeMs } = useRuntimeConfig();
  return useReportJobQuery(id, id ? queryStaleTimeMs : undefined);
}
import { useQuery } from '@tanstack/react-query';
import { api, requireData } from '../../api/client';

export function useReportContent(id: string, complete: boolean) {
  return useQuery({
    queryKey: ['reports', id, 'content'],
    enabled: Boolean(id) && complete,
    queryFn: async ({ signal }) => {
      const blob = requireData(
        await api.GET('/api/v1/reports/{report_id}/content', {
          params: { path: { report_id: id } },
          signal,
          parseAs: 'blob',
        }),
      );
      return { blob, html: blob.type.startsWith('text/html') ? await blob.text() : undefined };
    },
  });
}
