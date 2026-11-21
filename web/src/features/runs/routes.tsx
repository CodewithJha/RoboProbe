import type { RouteObject } from 'react-router-dom';
export const runRoutes: RouteObject[] = [{ path: 'runs/:id', lazy: () => import('./RunPage') }];
