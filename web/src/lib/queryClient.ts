/** Query policy: bounded network retries, never repeat server/client errors (T-085b). */
import { QueryClient } from '@tanstack/react-query';
import { getConfig } from './config';
import { ProblemError } from '../api/client';
export function createQueryClient(): QueryClient {
  const config = getConfig();
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: config.queryStaleTimeMs,
        retry: (count, error) =>
          !(error instanceof ProblemError) &&
          error instanceof TypeError &&
          count < config.queryRetryAttempts,
      },
      mutations: { retry: false },
    },
  });
}
