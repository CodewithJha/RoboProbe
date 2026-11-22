/** Global Vitest setup: DOM matchers and per-test cleanup. */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { resetKeyboardManager } from '../lib/keyboard';

afterEach(() => {
  cleanup();
  resetKeyboardManager();
});
