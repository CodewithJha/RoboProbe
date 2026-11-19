import type { JSX } from 'react';

/** Root component. Routing and providers arrive with the app shell (T-085b). */
export function App(): JSX.Element {
  return (
    <main>
      <h1>RoboProbe</h1>
      <p>Dashboard skeleton: feature screens land in milestone M8.</p>
    </main>
  );
}
