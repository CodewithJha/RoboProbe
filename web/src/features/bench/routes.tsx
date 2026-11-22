import type { RouteObject } from 'react-router-dom';
export const benchRoutes: RouteObject[] = [{ index: true, lazy: () => import('./BenchPage') }];
