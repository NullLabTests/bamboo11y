import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { to: "/", label: "Overview", end: true },
  { to: "/incidents", label: "Incidents", end: false },
  { to: "/signals", label: "Signals", end: false },
  { to: "/services", label: "Services", end: false },
  { to: "/integrations", label: "Integrations", end: false },
];

function Logo() {
  return (
    <span className="logo" aria-hidden="true">
      <svg viewBox="0 0 40 40" width="34" height="34" fill="none">
        <rect x="1" y="1" width="38" height="38" rx="11" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M8 24.5 14 18l5 4.5L23.5 12l4 7H33"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="14" cy="18" r="2" fill="currentColor" />
        <circle cx="23.5" cy="12" r="2" fill="currentColor" />
      </svg>
    </span>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="topbar">
        <div className="topbar__brand">
          <Logo />
          <div>
            <p className="topbar__name">Bamboo11y</p>
            <p className="topbar__tagline">Incident command center</p>
          </div>
        </div>
        <div className="topbar__status">
          <span className="pulse" aria-hidden="true" />
          <span>Local-first · rule-based correlation</span>
        </div>
      </header>
      <div className="shell-body">
        <nav className="sidebar" aria-label="Primary">
          <p className="sidebar__label">Workspace</p>
          <ul>
            {navigation.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? "nav-link is-active" : "nav-link")}
                >
                  <span className="nav-link__marker" aria-hidden="true" />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="sidebar__note">
            <p className="sidebar__note-title">Context, not cause</p>
            <p>
              Deployments near an incident are temporal context. Bamboo11y never claims that
              a change caused an outage.
            </p>
          </div>
        </nav>
        <main id="main-content" className="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <footer className="footer">
        <span>Bamboo11y · independent local-first AIOps demonstration</span>
        <span>No vendor affiliation · no external accounts required</span>
      </footer>
    </div>
  );
}
