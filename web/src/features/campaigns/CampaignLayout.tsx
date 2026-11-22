import { NavLink, Outlet, useParams } from 'react-router-dom';
const TABS = ['console', 'runs', 'casebook', 'atlas', 'insights', 'settings'] as const;
export function Component() {
  const { id } = useParams();
  return (
    <>
      <nav className="campaign-tabs" aria-label="Campaign sections">
        {TABS.map((tab) => (
          <NavLink key={tab} to={`/campaigns/${id ?? ''}/${tab}`}>
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}
