import { useEffect, useState, type PropsWithChildren } from 'react';
import { applyTheme, isThemePreference } from '../styles/theme';
import type { RuntimeConfig } from '../lib/config';
import { ThemeContext } from './contexts';
const STORAGE_KEY = 'roboprobe.theme';
export function ThemeProvider({ config, children }: PropsWithChildren<{ config: RuntimeConfig }>) {
  const [preference, setPreference] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return isThemePreference(stored) ? stored : config.defaultTheme;
    } catch {
      return config.defaultTheme;
    }
  });
  useEffect(() => {
    applyTheme(document.documentElement, preference);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      /* Private browsing may disable persistent preferences. */
    }
  }, [preference]);
  return <ThemeContext value={{ preference, setPreference }}>{children}</ThemeContext>;
}
