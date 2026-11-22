import {
  createContext,
  useContext,
  useSyncExternalStore,
  type PropsWithChildren,
} from 'react';

const KEY = 'roboprobe.number-locale';
const OPTIONS = ['system', 'en-US', 'de-DE'] as const;

export type NumberLocaleChoice = (typeof OPTIONS)[number];

function read(): NumberLocaleChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return OPTIONS.includes(stored as NumberLocaleChoice) ? (stored as NumberLocaleChoice) : 'system';
  } catch {
    return 'system';
  }
}

let current = read();
const listeners = new Set<() => void>();

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

export const numberLocaleOptions = OPTIONS;

const NumberLocaleContext = createContext({
  choice: current,
  setChoice: setNumberLocaleChoice,
});

export function useNumberLocale() {
  return useContext(NumberLocaleContext);
}

export function NumberLocaleProvider({ children }: PropsWithChildren) {
  const choice = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getNumberLocaleChoice,
    () => 'system' as const,
  );
  return (
    <NumberLocaleContext value={{ choice, setChoice: setNumberLocaleChoice }}>
      {children}
    </NumberLocaleContext>
  );
}