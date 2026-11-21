import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useRuntimeConfig, useSseStatus, useTheme } from './contexts';
import { RailHost } from './MarginRailSlot';
import './shell.css';
const NAVIGATION = [
  { to: '/', label: 'Bench', icon: 'M3 4h18v16H3zM3 9h18M8 9v11' },
  { to: '/campaigns', label: 'Campaigns', icon: 'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5' },
  { to: '/trials', label: 'Trials', icon: 'M8 3v6l-5 10h18L16 9V3M6 3h12M6 14h12' },
  { to: '/spaces', label: 'Spaces', icon: 'M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18' },
  { to: '/workbench', label: 'Workbench', icon: 'M4 6h16v12H4zM8 21h8M12 18v3M8 10h8' },
  { to: '/reports', label: 'Reports', icon: 'M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6' },
  { to: '/settings', label: 'Settings', icon: 'M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6' },
] as const;
export function Shell() {
  const config = useRuntimeConfig();
  const { preference, setPreference } = useTheme();
  const status = useSseStatus();
  const [host, setHost] = useState<HTMLElement | null>(null);
  const visible = NAVIGATION.filter(
    (item) =>
      (item.to !== '/trials' || config.featureFlags.trials) &&
      (item.to !== '/reports' || config.featureFlags.reports),
  );
  return (
    <RailHost value={host}>
      <a className="skip-link" href="#main-content">
        Skip to notebook
      </a>
      <div className="app-shell">
        <aside className="margin-rail">
          <NavLink className="brand" to="/" aria-label="RoboProbe Bench">
            <svg aria-hidden="true" viewBox="0 0 32 32">
              <path d="M5 24V8h10a7 7 0 0 1 0 14H5M15 22l10 7M2 5h27" />
            </svg>
            <span>
              RoboProbe<small>FIELD NOTEBOOK</small>
            </span>
          </NavLink>
          <nav aria-label="Main navigation">
            {visible.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                title={item.label}
                aria-label={item.label}
                className={({ isActive }) => `rail-link${isActive ? ' active' : ''}`}
              >
                <svg aria-hidden="true" viewBox="0 0 24 24">
                  <path d={item.icon} />
                </svg>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="rail-slot" ref={setHost} />
          <footer>
            <p className="connection">
              <span aria-hidden="true" className={`connection-dot ${status}`} />
              <span>Live: {status}</span>
            </p>
            <button
              className="theme-toggle"
              type="button"
              onClick={() => {
                setPreference(
                  preference === 'system' ? 'light' : preference === 'light' ? 'dark' : 'system',
                );
              }}
              aria-label={`Theme: ${preference}. Change theme`}
            >
              ◐{' '}
              <span>
                {preference === 'dark'
                  ? 'Night Shift'
                  : preference === 'light'
                    ? 'Paper'
                    : 'System theme'}
              </span>
            </button>
            <small className="rail-version">Reproducible by design</small>
          </footer>
        </aside>
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </RailHost>
  );
}
