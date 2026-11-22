import { Navigate, type RouteObject } from 'react-router-dom';
export const campaignRoutes: RouteObject[] = [
  { path: 'campaigns', lazy: () => import('./CampaignListPage') },
  { path: 'campaigns/new', lazy: () => import('./WizardPage') },
  {
    path: 'campaigns/:id',
    lazy: () => import('./CampaignLayout'),
    children: [
      { index: true, element: <Navigate to="console" replace /> },
      { path: 'console', lazy: () => import('../console/ConsolePage') },
      { path: 'runs', lazy: () => import('../runs/RunListPage') },
      { path: 'casebook', lazy: () => import('../casebook/CasebookPage') },
      { path: 'atlas', lazy: () => import('../atlas/AtlasPage') },
      { path: 'insights', lazy: () => import('../insights/InsightsPage') },
      { path: 'settings', lazy: () => import('../settings/SettingsPage') },
    ],
  },
];
