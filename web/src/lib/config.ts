/** Validated boot configuration (T-085d, NFR-DEP-001). */
import { isThemePreference, type ThemePreference } from '../styles/theme';

export interface RuntimeConfig {
  apiBaseUrl: string;
  sseUrl: string;
  defaultTheme: ThemePreference;
  featureFlags: { trials: boolean; reports: boolean };
  consoleReplayRepeats: number;
  wizardDefaultBudget: number;
  wizardDefaultRepeats: number;
  wizardSliderSteps: number;
  benchRecentLimit: number;
  benchRecentCaseCampaigns: number;
  queryStaleTimeMs: number;
  queryRetryAttempts: number;
  sseReconnectInitialMs: number;
  sseReconnectMaxMs: number;
  sseReconnectJitter: number;
  sseRecentEventLimit: number;
}

export const DEFAULT_CONFIG: RuntimeConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL,
  sseUrl: `${import.meta.env.VITE_API_BASE_URL}/events`,
  defaultTheme: 'system',
  featureFlags: { trials: true, reports: true },
  consoleReplayRepeats: 1,
  wizardDefaultBudget: 200,
  wizardDefaultRepeats: 1,
  wizardSliderSteps: 1000,
  benchRecentLimit: 10,
  benchRecentCaseCampaigns: 3,
  queryStaleTimeMs: 10_000,
  queryRetryAttempts: 2,
  sseReconnectInitialMs: 500,
  sseReconnectMaxMs: 30_000,
  sseReconnectJitter: 0.2,
  sseRecentEventLimit: 2048,
};
let current = DEFAULT_CONFIG;
export function getConfig(): RuntimeConfig {
  return current;
}
export function setConfig(config: RuntimeConfig): void {
  current = config;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function address(value: unknown, name: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Invalid ${name}`);
  const url = new URL(value, window.location.href);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
    throw new Error(`Invalid ${name}`);
  return value.replace(/\/$/, '');
}
export function parseConfig(raw: unknown): RuntimeConfig {
  if (!record(raw)) throw new Error('Runtime configuration must be an object');
  const config = { ...DEFAULT_CONFIG };
  config.apiBaseUrl = address(raw['apiBaseUrl'] ?? DEFAULT_CONFIG.apiBaseUrl, 'apiBaseUrl');
  config.sseUrl = address(raw['sseUrl'] ?? `${config.apiBaseUrl}/events`, 'sseUrl');
  const theme = raw['defaultTheme'] ?? DEFAULT_CONFIG.defaultTheme;
  if (!isThemePreference(theme)) throw new Error('Invalid defaultTheme');
  config.defaultTheme = theme;
  const flags = raw['featureFlags'] ?? DEFAULT_CONFIG.featureFlags;
  if (
    !record(flags) ||
    typeof flags['trials'] !== 'boolean' ||
    typeof flags['reports'] !== 'boolean'
  )
    throw new Error('Invalid featureFlags');
  config.featureFlags = { trials: flags['trials'], reports: flags['reports'] };
  const tunables = [
    'consoleReplayRepeats',
    'wizardDefaultBudget',
    'wizardDefaultRepeats',
    'wizardSliderSteps',
    'benchRecentLimit',
    'benchRecentCaseCampaigns',
    'queryStaleTimeMs',
    'queryRetryAttempts',
    'sseReconnectInitialMs',
    'sseReconnectMaxMs',
    'sseRecentEventLimit',
  ] as const;
  for (const key of tunables) {
    const value = raw[key] ?? DEFAULT_CONFIG[key];
    if (
      typeof value !== 'number' ||
      !Number.isSafeInteger(value) ||
      value < 0 ||
      (key !== 'queryRetryAttempts' && value === 0)
    )
      throw new Error(`Invalid ${key}`);
    config[key] = value;
  }
  const jitter = raw['sseReconnectJitter'] ?? DEFAULT_CONFIG.sseReconnectJitter;
  if (typeof jitter !== 'number' || !Number.isFinite(jitter) || jitter < 0 || jitter > 1)
    throw new Error('Invalid sseReconnectJitter');
  config.sseReconnectJitter = jitter;
  if (config.sseReconnectMaxMs < config.sseReconnectInitialMs)
    throw new Error('SSE reconnect maximum is smaller than initial delay');
  return config;
}
export async function loadConfig(fetcher: typeof fetch = fetch): Promise<RuntimeConfig> {
  let response: Response;
  try {
    response = await fetcher('/config.json', { cache: 'no-store' });
  } catch {
    current = { ...DEFAULT_CONFIG };
    return current;
  }
  if (response.status === 404) {
    current = { ...DEFAULT_CONFIG };
    return current;
  }
  if (!response.ok) throw new Error(`Runtime configuration failed (${String(response.status)})`);
  current = parseConfig((await response.json()) as unknown);
  return current;
}
