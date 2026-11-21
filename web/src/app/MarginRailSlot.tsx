import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
// eslint-disable-next-line react-refresh/only-export-components -- shared portal context
export const RailHost = createContext<HTMLElement | null>(null);
export function MarginRailSlot({ children }: { children: ReactNode }) {
  const host = useContext(RailHost);
  return host ? createPortal(children, host) : null;
}
