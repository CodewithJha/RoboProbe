import { createContext, useCallback, useContext, useRef, type PropsWithChildren } from 'react';

const SearchFocusContext = createContext<{
  register: (element: HTMLElement | null) => void;
  focus: () => void;
}>({ register: () => undefined, focus: () => undefined });

export function SearchFocusProvider({ children }: PropsWithChildren) {
  const target = useRef<HTMLElement | null>(null);
  const register = useCallback((element: HTMLElement | null) => {
    target.current = element;
  }, []);
  const focus = useCallback(() => {
    target.current?.focus();
  }, []);
  return <SearchFocusContext value={{ register, focus }}>{children}</SearchFocusContext>;
}

// eslint-disable-next-line react-refresh/only-export-components -- shared search focus hook
export function useSearchFocus() {
  return useContext(SearchFocusContext);
}
