import { useRuntimeConfig } from '../../app/contexts';
import { useReportJob as useReportJobQuery } from '../../api/hooks';

/** Poll an active report job until it leaves the running states (T-113b). */
export function useReportJob(id: string) {
  const { queryStaleTimeMs } = useRuntimeConfig();
  return useReportJobQuery(id, id ? queryStaleTimeMs : undefined);
}
