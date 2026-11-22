import type { RouteObject } from 'react-router-dom';
export const trialsRoutes: RouteObject[] = [
  { path: 'trials', lazy: () => import('./TrialsPage') },
  { path: 'trials/:id', lazy: () => import('./ExperimentPage') },
];
