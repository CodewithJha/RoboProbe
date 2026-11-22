import { createContext, useContext, useSyncExternalStore, type PropsWithChildren } from 'react';
import {
  getNumberLocaleChoice,
  setNumberLocaleChoice,
  subscribeNumberLocale,
} from './numberLocale';

const NumberLocaleContext = createContext({
  choice: getNumberLocaleChoice(),
  setChoice: setNumberLocaleChoice,
});

// eslint-disable-next-line react-refresh/only-export-components -- shared locale context
export function useNumberLocale() {
  return useContext(NumberLocaleContext);
}

export function NumberLocaleProvider({ children }: PropsWithChildren) {
  const choice = useSyncExternalStore(
    subscribeNumberLocale,
    getNumberLocaleChoice,
    () => 'system' as const,
  );
  return (
    <NumberLocaleContext value={{ choice, setChoice: setNumberLocaleChoice }}>
      {children}
    </NumberLocaleContext>
  );
}
