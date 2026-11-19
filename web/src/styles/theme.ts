/**
 * Theme selection (doc 27 §4.11 `defaultTheme`): `light`, `dark`, or `system` (follow the OS).
 */
import { THEMES, type ThemeName } from './tokens';

export const THEME_PREFERENCES = [...THEMES, 'system'] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

const THEME_ATTRIBUTE = 'data-theme';

/** Type guard for values read from runtime config or storage. */
export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === 'string' && (THEME_PREFERENCES as readonly string[]).includes(value);
}

/**
 * Applies a preference to `root`: an explicit theme sets `data-theme`; `system` removes it so the
 * `prefers-color-scheme` rule in `tokens.css` decides.
 */
export function applyTheme(root: HTMLElement, preference: ThemePreference): void {
  if (preference === 'system') {
    root.removeAttribute(THEME_ATTRIBUTE);
  } else {
    root.setAttribute(THEME_ATTRIBUTE, preference satisfies ThemeName);
  }
}
