import type { RouteObject } from 'react-router-dom';
export const reportsRoutes: RouteObject[] = [
  { path: 'reports', lazy: () => import('./ReportsPage') },
  { path: 'reports/:id', lazy: () => import('./ReportPage') },
];
