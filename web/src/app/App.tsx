import { useState } from 'react';
import { RouterProvider } from 'react-router-dom';
import { AppProviders } from './providers';
import { createAppRouter } from './router';
/** Mounted only after runtime configuration has been validated. */
export function App() {
  const [router] = useState(createAppRouter);
  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
