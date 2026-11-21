import type { RouteObject } from 'react-router-dom';
export const spacesRoutes: RouteObject[] = [
  { path: 'spaces', lazy: () => import('./SpacesPage') },
  { path: 'spaces/:id/:version', lazy: () => import('./SpacePage') },
];
