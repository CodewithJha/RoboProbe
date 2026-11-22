/** Context contracts shared with feature modules. */
import { createContext, useContext, useSyncExternalStore } from 'react';
import type { ThemePreference } from '../styles/theme';
import type { SseClient } from '../lib/sse';
import { DEFAULT_CONFIG, type RuntimeConfig } from '../lib/config';
export const RuntimeContext = createContext<RuntimeConfig>(DEFAULT_CONFIG);
export const ThemeContext = createContext<{
  preference: ThemePreference;
  setPreference: (theme: ThemePreference) => void;
}>({ preference: 'system', setPreference: () => undefined });
export const SseContext = createContext<SseClient | null>(null);
export function useRuntimeConfig(): RuntimeConfig {
  return useContext(RuntimeContext);
}
export function useTheme() {
  return useContext(ThemeContext);
}
export function useSseStatus() {
  const source = useContext(SseContext);
  return useSyncExternalStore(
    source?.subscribe ?? (() => () => undefined),
    source?.snapshot ?? (() => 'closed' as const),
  );
}
