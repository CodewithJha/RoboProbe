/** Browser entry point: mounts <App/> into #root. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import { loadConfig } from './lib/config';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/print.css';

const ROOT_ELEMENT_ID = 'root';

const container = document.getElementById(ROOT_ELEMENT_ID);
if (container === null) {
  throw new Error(`Missing #${ROOT_ELEMENT_ID} element in index.html`);
}

const root = createRoot(container);
void loadConfig()
  .then(() => {
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  })
  .catch(() => {
    root.render(
      <main role="alert">
        <h1>Configuration could not be loaded</h1>
        <p>Check config.json and reload this page.</p>
      </main>,
    );
  });
