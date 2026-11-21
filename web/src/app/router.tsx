import { createBrowserRouter, type RouteObject } from 'react-router-dom';
import type { ComponentType } from 'react';
import { Shell } from './Shell';
import { NotFound } from './NotFound';
import { RouteError } from './ProblemView';
import { benchRoutes } from '../features/bench/routes';
import { campaignRoutes } from '../features/campaigns/routes';
import { runRoutes } from '../features/runs/routes';
import { trialsRoutes } from '../features/trials/routes';
import { spacesRoutes } from '../features/spaces/routes';
import { workbenchRoutes } from '../features/workbench/routes';
import { reportsRoutes } from '../features/reports/routes';
import { settingsRoutes } from '../features/settings/routes';
import { getConfig } from '../lib/config';
// Component task #167 supplies this development-only module in a separate stacked PR.
const galleries = import.meta.env.DEV
  ? import.meta.glob<{ ComponentGallery: ComponentType }>('../components/ComponentGallery.tsx')
  : {};
const gallery = galleries['../components/ComponentGallery.tsx'];
export function appRoutes(): RouteObject[] {
  const config = getConfig();
  return [
    {
      path: '/',
      Component: Shell,
      ErrorBoundary: RouteError,
      children: [
        ...benchRoutes,
        ...campaignRoutes,
        ...runRoutes,
        ...spacesRoutes,
        ...workbenchRoutes,
        ...settingsRoutes,
        ...(config.featureFlags.trials ? trialsRoutes : []),
        ...(config.featureFlags.reports ? reportsRoutes : []),
        ...(gallery
          ? [
              {
                path: 'dev/components',
                lazy: async () => ({ Component: (await gallery()).ComponentGallery }),
              },
            ]
          : []),
        { path: '*', Component: NotFound },
      ],
    },
  ];
}
export function createAppRouter() {
  return createBrowserRouter(appRoutes());
}
