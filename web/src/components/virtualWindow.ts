import { componentConfig } from './config';

/** Bounded first-paint window while the scroll viewport is not measured (SSR/hidden tabs). */
export function initialVirtualWindow(count: number, height: number, itemSize: number) {
  const visible = Math.min(count, Math.ceil(height / itemSize) + componentConfig.overscan);
  return Array.from({ length: visible }, (_, index) => ({
    index,
    key: index,
    start: index * itemSize,
    end: (index + 1) * itemSize,
    size: itemSize,
  }));
}
