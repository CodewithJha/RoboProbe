const KEY = 'roboprobe.number-locale';
const OPTIONS = ['system', 'en-US', 'de-DE'] as const;

export type NumberLocaleChoice = (typeof OPTIONS)[number];

let current: NumberLocaleChoice = read();
const listeners = new Set<() => void>();

function read(): NumberLocaleChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return OPTIONS.includes(stored as NumberLocaleChoice)
      ? (stored as NumberLocaleChoice)
      : 'system';
  } catch {
    return 'system';
  }
}

export function getNumberLocale(): string | undefined {
  return current === 'system' ? undefined : current;
}

export function getNumberLocaleChoice(): NumberLocaleChoice {
  return current;
}

export function setNumberLocaleChoice(choice: NumberLocaleChoice): void {
  if (!OPTIONS.includes(choice)) return;
  current = choice;
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* Private browsing may block storage. */
  }
  listeners.forEach((listener) => {
    listener();
  });
}

export function subscribeNumberLocale(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const numberLocaleOptions = OPTIONS;
