import type { RouteObject } from 'react-router-dom';
export const workbenchRoutes: RouteObject[] = [
  { path: 'workbench', lazy: () => import('./WorkbenchPage') },
];
