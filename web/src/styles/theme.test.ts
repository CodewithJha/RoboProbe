import { describe, expect, it } from 'vitest';

import { applyTheme, isThemePreference } from './theme';

describe('applyTheme', () => {
  it('sets data-theme for an explicit theme and clears it for system', () => {
    const root = document.createElement('html');
    applyTheme(root, 'dark');
    expect(root.dataset['theme']).toBe('dark');
    applyTheme(root, 'light');
    expect(root.dataset['theme']).toBe('light');
    applyTheme(root, 'system');
    expect(root.hasAttribute('data-theme')).toBe(false);
  });
});

describe('isThemePreference', () => {
  it.each(['light', 'dark', 'system'])('accepts %j', (value) => {
    expect(isThemePreference(value)).toBe(true);
  });

  it.each(['Dark', '', null, 1, undefined])('rejects %j', (value) => {
    expect(isThemePreference(value)).toBe(false);
  });
});
