import { useEffect, useState, type PropsWithChildren } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@radix-ui/react-tooltip';
import { createQueryClient } from '../lib/queryClient';
import { getConfig, type RuntimeConfig } from '../lib/config';
import { SseClient } from '../lib/sse';
import { bindSse } from '../lib/sseBridge';
import { NumberLocaleProvider } from '../lib/numberLocale';
import { RuntimeContext, SseContext } from './contexts';
import { SearchFocusProvider } from './SearchFocusContext';
import { ThemeProvider } from './ThemeProvider';
export function AppProviders({
  children,
  config = getConfig(),
  live = true,
}: PropsWithChildren<{ config?: RuntimeConfig; live?: boolean }>) {
  const [queryClient] = useState(createQueryClient);
  const [source] = useState(() => new SseClient(config));
  useEffect(() => {
    if (!live) return;
    const unbind = bindSse(queryClient, source);
    const reconnect = () => {
      source.connect();
    };
    source.connect();
    window.addEventListener('roboprobe-token-changed', reconnect);
    return () => {
      unbind();
      source.disconnect();
      window.removeEventListener('roboprobe-token-changed', reconnect);
    };
  }, [queryClient, source, live]);
  return (
    <RuntimeContext value={config}>
      <QueryClientProvider client={queryClient}>
        <SearchFocusProvider>
          <ThemeProvider config={config}>
            <NumberLocaleProvider>
              <TooltipProvider>
                <SseContext value={source}>{children}</SseContext>
              </TooltipProvider>
            </NumberLocaleProvider>
          </ThemeProvider>
        </SearchFocusProvider>
      </QueryClientProvider>
    </RuntimeContext>
  );
}
