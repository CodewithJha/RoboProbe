/** Browser entry point: mounts <App/> into #root. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';

const ROOT_ELEMENT_ID = 'root';

const container = document.getElementById(ROOT_ELEMENT_ID);
if (container === null) {
  throw new Error(`Missing #${ROOT_ELEMENT_ID} element in index.html`);
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
